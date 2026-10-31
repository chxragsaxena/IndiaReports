"""Queuing the emails this system sends, and what they say."""

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.mailer import clean_header, email_enabled
from app.models.email import EmailJob
from app.models.report import Report


async def queue_email(db: AsyncSession, to: str | None, subject: str, body: str, dedupe_key: str) -> None:
    """Stage an email in the caller's transaction. The same dedupe_key is only ever queued
    once, so a retried request cannot send the same notice twice. Does nothing when email
    is not configured or there is nobody to send to (anonymous reports have no address)."""
    if not to or not email_enabled():
        return
    await db.execute(
        insert(EmailJob)
        .values(to_email=to, subject=clean_header(subject), body=body, dedupe_key=dedupe_key[:120])
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )


def _link(path: str) -> str:
    base = settings.PUBLIC_APP_URL.rstrip("/")
    return f"{base}{path}" if base else ""


def _days(seconds: int) -> str:
    days = seconds / 86400
    if days >= 1:
        n = round(days)
        return f"{n} day{'s' if n != 1 else ''}"
    hours = max(1, round(seconds / 3600))
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _where(report: Report) -> str:
    return ", ".join(p for p in (report.address, report.city, report.state) if p) or "the location you marked"


def resolved_notice(report: Report, name: str) -> tuple[str, str]:
    note = f'\nWhat was done: "{report.resolution_note}"\n' if report.resolution_note else ""
    link = _link("/my-reports")
    return (
        f"Resolved: {report.title}",
        f"Hello {name},\n\n"
        f'The issue you reported, "{report.title}" at {_where(report)}, has been marked as resolved.\n'
        f"{note}\n"
        f"It stays visible on the map for {_days(settings.RESOLVED_VISIBLE_SECONDS)} so you can check it. "
        f"If it is fixed, you can confirm it. If it is not, you can reopen it and it goes straight back to the "
        f"officer responsible.\n"
        + (f"\nCheck it here: {link}\n" if link else "")
        + "\nThank you for reporting.\nIndiaReports",
    )


def reopened_notice(report: Report, officer_name: str, reason: str | None) -> tuple[str, str]:
    link = _link("/admin")
    why = f'\nThe citizen says: "{reason}"\n' if reason else ""
    return (
        f"Reopened: {report.title}",
        f"Hello {officer_name},\n\n"
        f'The citizen who reported "{report.title}" at {_where(report)} says it is not fixed, so it is open '
        f"again. The {_days(settings.ESCALATION_AFTER_SECONDS)} clock has restarted.\n"
        f"{why}"
        + (f"\nOpen your queue: {link}\n" if link else "")
        + "\nIndiaReports",
    )


def assigned_notice(report: Report, officer_name: str) -> tuple[str, str]:
    link = _link("/admin")
    return (
        f"New report in your area: {report.title}",
        f"Hello {officer_name},\n\n"
        f'A new {report.category.lower()} issue was reported in your area: "{report.title}" at {_where(report)}.\n\n'
        f"Please resolve it within {_days(settings.ESCALATION_AFTER_SECONDS)}. After that it is escalated to the "
        f"main administrator.\n"
        + (f"\nOpen your queue: {link}\n" if link else "")
        + "\nIndiaReports",
    )


def escalated_notice(report: Report, admin_name: str, previous: str, since: datetime | None) -> tuple[str, str]:
    link = _link("/admin")
    return (
        f"Escalated: {report.title}",
        f"Hello {admin_name},\n\n"
        f'"{report.title}" at {_where(report)} was not resolved within {_days(settings.ESCALATION_AFTER_SECONDS)} '
        f"by {previous}, so it has been escalated to you.\n"
        + (f"\nOpen the queue: {link}\n" if link else "")
        + "\nIndiaReports",
    )


def reset_notice(name: str, secret: str) -> tuple[str, str]:
    link = _link(f"/reset-password?token={secret}")
    return (
        "Reset your IndiaReports password",
        f"Hello {name},\n\n"
        "Someone asked to reset the password for this account. If that was you, open this link within one hour "
        "and choose a new password:\n\n"
        f"{link or '(the site address is not configured, ask the administrator)'}\n\n"
        "The link works once. If you did not ask for this, ignore this email: your password has not changed.\n\n"
        "IndiaReports",
    )


def verify_notice(name: str, secret: str) -> tuple[str, str]:
    link = _link(f"/verify-email?token={secret}")
    return (
        "Confirm your email for IndiaReports",
        f"Hello {name},\n\n"
        "Confirm this email address so we can tell you when the problems you report are resolved:\n\n"
        f"{link or '(the site address is not configured, ask the administrator)'}\n\n"
        "The link works for 2 days. If you did not create an account, ignore this email.\n\n"
        "IndiaReports",
    )
