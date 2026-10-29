import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user_optional
from app.core.config import settings
from app.db.session import get_db
from app.models.area import Officer
from app.models.report import Report
from app.models.user import User


@dataclass
class Staff:
    """Who is acting on reports. The main admin (and the service API key) see everything;
    an area officer sees and acts on only the reports assigned to them."""

    user: User | None
    officer: Officer | None  # the officer record behind an area officer's account
    is_main: bool

    def can_see(self, report: Report) -> bool:
        return self.is_main or (self.officer is not None and report.assigned_officer_id == self.officer.id)


async def require_staff(
    x_api_key: str | None = Header(default=None),
    user: User | None = Depends(current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> Staff:
    """A signed-in administrator or area officer, or the service API key (scripts, tests,
    break-glass). A signed-in citizen is refused even if they also send a key."""
    if user is not None:
        if user.role == "admin":
            return Staff(user=user, officer=None, is_main=True)
        if user.role == "officer":
            officer = (
                await db.execute(select(Officer).where(Officer.user_id == user.id, Officer.active.is_(True)))
            ).scalar_one_or_none()
            if officer is None:
                raise HTTPException(status_code=403, detail="Your account is not linked to an area yet. Ask the administrator.")
            return Staff(user=user, officer=officer, is_main=False)
        raise HTTPException(status_code=403, detail="Administrator access required.")

    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Please sign in as an administrator.")
    return Staff(user=None, officer=None, is_main=True)


async def require_admin(staff: Staff = Depends(require_staff)) -> Staff:
    """The main administrator only: managing areas, officers and accounts."""
    if not staff.is_main:
        raise HTTPException(status_code=403, detail="Only the main administrator can do this.")
    return staff
