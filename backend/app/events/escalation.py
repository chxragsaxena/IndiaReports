"""Escalates reports that nobody acknowledged in time to the main admin."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.events.outbox import add_event, escalated_payload
from app.models.area import Officer
from app.models.enums import ReportStatus
from app.models.report import Report
from app.services.assignment_service import get_admin, recipient_for

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def escalate_once() -> int:
    """Reassign overdue, unacknowledged reports to the admin and emit ReportEscalated.

    Safe to run on many instances at once (rows are claimed with SKIP LOCKED), and
    safe to run repeatedly: a report escalates at most once. Returns how many moved."""
    async with AsyncSessionLocal() as db:
        admin = await get_admin(db)
        if admin is None:
            return 0  # nobody to escalate to; reports stay where they are

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=settings.ESCALATION_AFTER_SECONDS)

        reports = (
            await db.execute(
                select(Report)
                .where(
                    Report.status == ReportStatus.OPEN.value,
                    Report.acknowledged_at.is_(None),
                    Report.escalated_at.is_(None),
                    Report.assigned_officer_id.is_not(None),
                    Report.assigned_officer_id != admin.id,
                    Report.assigned_at <= cutoff,
                )
                .order_by(Report.assigned_at)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for report in reports:
            previous = await db.get(Officer, report.assigned_officer_id)
            waited = (now - report.assigned_at).total_seconds()

            report.escalated_at = now
            report.assigned_officer_id = admin.id
            add_event(
                db,
                "ReportEscalated",
                escalated_payload(
                    report,
                    recipient=recipient_for(report, admin),
                    previous_assignee=previous.name if previous else "unassigned",
                    unacknowledged_seconds=waited,
                ),
            )

        await db.commit()
        return len(reports)


async def run_escalation(stop: asyncio.Event) -> None:
    """Background loop. Errors only delay escalation; they never raise."""
    while not stop.is_set():
        try:
            moved = await escalate_once()
            if moved:
                logger.info("escalated %d unacknowledged reports to the admin", moved)
        except Exception:
            logger.warning("escalation run failed, will retry", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.ESCALATION_CHECK_SECONDS)
        except asyncio.TimeoutError:
            pass
