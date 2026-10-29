import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis
from app.db.session import AsyncSessionLocal
from app.models.outbox import OutboxEvent
from app.models.report import Report

logger = logging.getLogger(__name__)

BATCH_SIZE = 200
IDLE_SLEEP = 0.5
MAX_BACKOFF = 15.0


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def report_created_payload(report: Report) -> dict:
    return {
        "report_id": str(report.id),
        "title": report.title,
        "category": report.category,
        "status": report.status,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "city": report.city,
        "state": report.state,
        "pincode": report.pincode,
        "created_at": _iso(report.created_at),
    }


def status_changed_payload(report: Report, old_status: str, changed_at: datetime) -> dict:
    return {
        "report_id": str(report.id),
        "title": report.title,
        "category": report.category,
        "old_status": old_status,
        "new_status": report.status,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "city": report.city,
        "state": report.state,
        "pincode": report.pincode,
        "created_at": _iso(report.created_at),
        "changed_at": _iso(changed_at),
    }


def add_event(db: AsyncSession, event_type: str, payload: dict) -> None:
    """Stage an event in the caller's transaction."""
    db.add(OutboxEvent(event_type=event_type, payload=payload))


async def relay_once() -> int:
    """Publish a batch of unpublished events. Safe to run on many instances at once:
    rows are claimed with FOR UPDATE SKIP LOCKED. Returns the number published."""
    redis = get_redis()
    if redis is None:
        return 0

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        if not rows:
            return 0

        pipe = redis.pipeline()
        for row in rows:
            pipe.xadd(
                settings.EVENT_STREAM,
                {
                    "event_id": str(row.id),
                    "type": row.event_type,
                    "data": json.dumps(row.payload),
                },
                maxlen=settings.EVENT_STREAM_MAXLEN,
                approximate=True,
            )
        await pipe.execute()

        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id.in_([r.id for r in rows]))
            .values(published_at=func.now())
        )
        await session.commit()
        return len(rows)


async def run_relay(stop: asyncio.Event) -> None:
    """Background loop. A Redis or DB error only delays delivery; it never raises."""
    if get_redis() is None:
        logger.info("REDIS_URL not set: outbox relay disabled, events stay in outbox")
        return

    backoff = IDLE_SLEEP
    while not stop.is_set():
        try:
            published = await relay_once()
            backoff = IDLE_SLEEP
            if published == BATCH_SIZE:
                continue  # a full batch means more may be waiting
        except Exception:
            logger.warning("outbox relay failed, retrying", exc_info=True)
            backoff = min(backoff * 2, MAX_BACKOFF)
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
