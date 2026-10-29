"""Background worker: sends each uploaded photo to the vision model and records the findings.

It runs off the request path, so uploads stay fast whatever the model does. Safe to run on
many instances at once (rows are claimed with SKIP LOCKED). Failures retry with backoff,
and a daily cap keeps a spike from exhausting the model server.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from app.analysis.analyzer import AnalysisError, Analyzer, ReportContext
from app.analysis.schema import needs_admin_attention
from app.core.config import settings
from app.core.storage import ObjectStore, get_store
from app.db.session import AsyncSessionLocal
from app.events.outbox import add_event
from app.models.image import ReportImage
from app.models.report import Report
from app.services.assignment_service import get_admin

logger = logging.getLogger(__name__)

CLAIM_TIMEOUT = timedelta(minutes=15)  # a crashed worker's claim is released after this
RETRY_BACKOFF = (60, 300, 1800)  # seconds before attempt 2, 3, ...


async def _analyses_today(db) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (await db.execute(select(func.count()).select_from(ReportImage).where(ReportImage.analyzed_at >= start))).scalar_one()


async def claim_batch(limit: int) -> list[ReportImage]:
    """Mark up to `limit` ready photos as being analysed and return them."""
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Release claims left behind by a worker that died mid-analysis.
        await db.execute(
            update(ReportImage)
            .where(ReportImage.status == "analyzing", ReportImage.claimed_at < now - CLAIM_TIMEOUT)
            .values(status="pending", claimed_at=None)
        )

        remaining = settings.ANALYSIS_MAX_PER_DAY - await _analyses_today(db)
        if remaining <= 0:
            await db.commit()
            return []

        rows = (
            await db.execute(
                select(ReportImage)
                .where(ReportImage.status == "pending", ReportImage.next_attempt_at <= now)
                .order_by(ReportImage.created_at)
                .limit(min(limit, remaining))
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for row in rows:
            row.status = "analyzing"
            row.claimed_at = now
        await db.commit()
        return list(rows)


async def _finish(image_id, **values) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(ReportImage).where(ReportImage.id == image_id).values(**values))
        await db.commit()


async def analyze_one(image: ReportImage, analyzer: Analyzer, store: ObjectStore) -> None:
    attempts = image.attempts + 1
    try:
        async with AsyncSessionLocal() as db:
            report = await db.get(Report, image.report_id)
        if report is None:
            await _finish(image.id, status="failed", attempts=attempts, error="The report no longer exists.")
            return

        data = await store.get(image.storage_key)
        findings = await analyzer.analyze(
            data, image.content_type, ReportContext(report.title, report.description, report.category)
        )
    except AnalysisError as e:
        give_up = (not e.retryable) or attempts >= settings.ANALYSIS_MAX_ATTEMPTS
        logger.warning("analysis of %s failed (attempt %d, %s): %s", image.id, attempts,
                       "giving up" if give_up else "will retry", e)
        await _finish(
            image.id,
            status="failed" if give_up else "pending",
            attempts=attempts,
            claimed_at=None,
            error=str(e)[:500],
            next_attempt_at=datetime.now(timezone.utc)
            + timedelta(seconds=RETRY_BACKOFF[min(attempts - 1, len(RETRY_BACKOFF) - 1)]),
        )
        return
    except Exception as e:  # storage hiccup, bug: treat like a retryable failure, never crash the loop
        logger.exception("unexpected error analysing %s", image.id)
        give_up = attempts >= settings.ANALYSIS_MAX_ATTEMPTS
        await _finish(image.id, status="failed" if give_up else "pending", attempts=attempts, claimed_at=None,
                      error=f"Unexpected error: {e.__class__.__name__}",
                      next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=RETRY_BACKOFF[0]))
        return

    # Success: store the findings and, if they are serious, queue a message to the admin.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ReportImage)
            .where(ReportImage.id == image.id)
            .values(
                status="done", attempts=attempts, claimed_at=None, error=None,
                severity=findings.severity, analysis=findings.model_dump(),
                analysis_provider=analyzer.provider, analysis_model=analyzer.model,
                analyzed_at=datetime.now(timezone.utc),
            )
        )
        report = await db.get(Report, image.report_id)
        if report is not None and needs_admin_attention(findings):
            admin = await get_admin(db)
            payload = {
                "report_id": str(report.id), "title": report.title, "category": report.category,
                "city": report.city, "state": report.state, "pincode": report.pincode,
                "latitude": report.latitude, "longitude": report.longitude,
                "image_id": str(image.id), "severity": findings.severity, "summary": findings.summary,
                "provider": analyzer.provider,
            }
            if admin is not None and analyzer.provider != "mock":  # demo output must never page anyone
                payload["recipient"] = {
                    "officer_id": str(admin.id), "name": admin.name, "role": admin.role,
                    "chat_id": admin.telegram_chat_id, "ack_token": None,
                }
            add_event(db, "ReportImageAnalyzed", payload)
        await db.commit()


async def analyze_batch(analyzer: Analyzer, store: ObjectStore) -> int:
    batch = await claim_batch(settings.ANALYSIS_CONCURRENCY)
    if batch:
        await asyncio.gather(*(analyze_one(img, analyzer, store) for img in batch))
    return len(batch)


async def run_analysis(stop: asyncio.Event, analyzer: Analyzer | None) -> None:
    """Background loop. Errors only delay analysis; they never raise."""
    if analyzer is None:
        logger.info("photo analysis is off: photos are stored, findings are not produced")
        return
    logger.info("photo analysis on: provider=%s model=%s", analyzer.provider, analyzer.model)
    while not stop.is_set():
        try:
            store = get_store()
            handled = await analyze_batch(analyzer, store) if store is not None else 0
        except Exception:
            logger.warning("analysis loop error, retrying", exc_info=True)
            handled = 0
        if handled == 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
