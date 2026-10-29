"""Applies report events to the grid rollup, in batches, off the request path.

Keeping this out of the request transaction is what lets writes scale: a request only
inserts the report and an outbox row. Here many events collapse into a few hundred
row updates, applied by one batch at a time, so hot map cells are no longer a lock
every writer has to queue on. The cost is that the map and dashboard lag by about a
second, which is invisible next to their cache TTL.
"""

import asyncio
import logging

from sqlalchemy import delete, func, select, update

from app.core.redis import get_redis
from app.db.session import AsyncSessionLocal
from app.models.outbox import OutboxEvent
from app.services.cell_service import apply_deltas

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
IDLE_SLEEP = 1.0
MAX_BACKOFF = 15.0
PRUNE_EVERY_SECONDS = 600
KEEP_DAYS = 3


def _changes(event_type: str, p: dict) -> list[tuple[float, float, str, str, int]]:
    lat, lng, category = p.get("latitude"), p.get("longitude"), p.get("category")
    if lat is None or lng is None or category is None:
        return []
    if event_type == "ReportCreated" and p.get("status"):
        return [(lat, lng, p["status"], category, 1)]
    if event_type == "ReportStatusChanged" and p.get("old_status") and p.get("new_status"):
        return [(lat, lng, p["old_status"], category, -1), (lat, lng, p["new_status"], category, 1)]
    if event_type == "ReportArchived" and p.get("new_status"):
        return [(lat, lng, p["new_status"], category, -1)]  # leaves the map: counted nowhere
    return []


async def rollup_once() -> int:
    """Fold one batch of not-yet-applied events into the rollup. Safe on many instances
    at once (rows are claimed with SKIP LOCKED). Returns the number of events handled."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.rolled_up_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        if not rows:
            return 0

        changes = []
        for row in rows:
            changes.extend(_changes(row.event_type, row.payload))
        await apply_deltas(db, changes)

        await db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id.in_([r.id for r in rows]))
            .values(rolled_up_at=func.now())
        )
        await db.commit()
        return len(rows)


async def prune_outbox() -> int:
    """Delete events that were applied (and published, when Redis is in use) long ago."""
    async with AsyncSessionLocal() as db:
        cutoff = func.now() - func.make_interval(0, 0, 0, KEEP_DAYS)
        stmt = delete(OutboxEvent).where(OutboxEvent.rolled_up_at < cutoff)
        if get_redis() is not None:
            stmt = stmt.where(OutboxEvent.published_at.is_not(None))
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0


async def run_rollup(stop: asyncio.Event) -> None:
    """Background loop. Errors only delay the map; they never raise."""
    backoff = IDLE_SLEEP
    since_prune = 0.0
    while not stop.is_set():
        try:
            handled = await rollup_once()
            backoff = IDLE_SLEEP
            if handled == BATCH_SIZE:
                continue  # a full batch means more is waiting
            if since_prune >= PRUNE_EVERY_SECONDS:
                since_prune = 0.0
                pruned = await prune_outbox()
                if pruned:
                    logger.info("pruned %d old outbox events", pruned)
        except Exception:
            logger.warning("rollup run failed, retrying", exc_info=True)
            backoff = min(backoff * 2, MAX_BACKOFF)
        since_prune += backoff
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
