"""Who is responsible for a report, acknowledging it, and escalating when ignored."""

import hmac
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.events.outbox import add_event, status_changed_payload
from app.models.area import Area, Officer
from app.models.enums import ReportStatus
from app.models.report import Report


def _secret() -> bytes | None:
    secret = settings.ACK_SECRET or settings.ADMIN_API_KEY
    return secret.encode() if secret else None


def ack_token(report_id: uuid.UUID, officer_id: uuid.UUID) -> str | None:
    """Signed token tying one report to one officer. Sent inside the alert link, so
    the officer needs no login. Reassigning the report invalidates the old token."""
    secret = _secret()
    if secret is None:
        return None
    return hmac.new(secret, f"{report_id}:{officer_id}".encode(), hashlib.sha256).hexdigest()


def recipient_for(report: Report, officer: Officer) -> dict:
    return {
        "officer_id": str(officer.id),
        "name": officer.name,
        "role": officer.role,
        "chat_id": officer.telegram_chat_id or "",
        "ack_token": ack_token(report.id, officer.id),
    }


async def get_admin(db: AsyncSession) -> Officer | None:
    result = await db.execute(
        select(Officer).where(Officer.role == "admin", Officer.active.is_(True)).limit(1)
    )
    return result.scalar_one_or_none()


async def find_assignee(db: AsyncSession, latitude: float, longitude: float) -> Officer | None:
    """The active officer of the smallest area containing the point, else the admin."""
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    result = await db.execute(
        select(Officer)
        .join(Area, Area.id == Officer.area_id)
        .where(Officer.active.is_(True), func.ST_Contains(Area.geom, point))
        .order_by(func.ST_Area(Area.geom).asc(), Officer.created_at.asc())
        .limit(1)
    )
    officer = result.scalar_one_or_none()
    return officer or await get_admin(db)


class AckError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


async def acknowledge(db: AsyncSession, report_id: uuid.UUID, token: str) -> Report:
    report = (
        await db.execute(select(Report).where(Report.id == report_id).with_for_update())
    ).scalar_one_or_none()
    if report is None:
        raise AckError(404, "Report not found.")
    if report.assigned_officer_id is None:
        raise AckError(409, "This report has no assignee.")

    expected = ack_token(report.id, report.assigned_officer_id)
    if expected is None:
        raise AckError(503, "Acknowledgement is not configured.")
    if not hmac.compare_digest(expected, token):
        # Also covers a stale link after the report was escalated to someone else.
        raise AckError(403, "This acknowledgement link is invalid or has been superseded.")

    if report.acknowledged_at is not None:
        return report  # idempotent

    now = datetime.now(timezone.utc)
    report.acknowledged_at = now
    if report.status == ReportStatus.OPEN.value:
        report.status = ReportStatus.IN_PROGRESS.value
        add_event(db, "ReportStatusChanged", status_changed_payload(report, ReportStatus.OPEN.value, now))
    await db.commit()
    await db.refresh(report)
    return report
