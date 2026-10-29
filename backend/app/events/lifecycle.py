"""Takes resolved reports off the public map once the citizen has had time to check them."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.events.outbox import add_event, status_changed_payload
from app.models.enums import ReportStatus
from app.models.report import Report

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


async def archive_once() -> int:
    """Archive resolved reports whose window has passed, or that the reporter confirmed.

    "Archived" means off the map and out of the counts; the report itself is kept and stays
    in the reporter's and officers' lists. Safe on many instances at once (SKIP LOCKED) and
    safe to repeat. Returns how many were archived."""
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=settings.RESOLVED_VISIBLE_SECONDS)

        reports = (
            await db.execute(
                select(Report)
                .where(
                    Report.status == ReportStatus.RESOLVED.value,
                    Report.archived_at.is_(None),
                    or_(Report.resolved_at <= cutoff, Report.confirmed_at.is_not(None)),
                )
                .order_by(Report.resolved_at)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for report in reports:
            report.archived_at = now
            # The rollup removes it from the map counts; viewers with it open simply stop seeing it.
            add_event(db, "ReportArchived", status_changed_payload(report, report.status, now))

        await db.commit()
        return len(reports)


async def run_lifecycle(stop: asyncio.Event) -> None:
    """Background loop. Errors only delay the cleanup; they never raise."""
    while not stop.is_set():
        try:
            archived = await archive_once()
            if archived:
                logger.info("archived %d resolved reports off the map", archived)
        except Exception:
            logger.warning("lifecycle run failed, will retry", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.LIFECYCLE_CHECK_SECONDS)
        except asyncio.TimeoutError:
            pass
