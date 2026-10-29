import hmac

from fastapi import Depends, Header, HTTPException

from app.core.auth import current_user_optional
from app.core.config import settings
from app.models.user import User


async def require_admin(
    x_api_key: str | None = Header(default=None),
    user: User | None = Depends(current_user_optional),
) -> None:
    """Allows a signed-in admin, or the service API key (scripts, tests, break-glass).
    A signed-in non-admin is refused even if they also send a key."""
    if user is not None:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Administrator access required.")
        return

    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Please sign in as an administrator.")
