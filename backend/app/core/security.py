import hmac

from fastapi import Header, HTTPException

from app.core.config import settings


async def require_admin(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="Admin API is not configured.")
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key.")
