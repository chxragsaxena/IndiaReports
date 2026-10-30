import logging

from fastapi import Depends, HTTPException, Request

from app.core.auth import require_user
from app.core.config import settings
from app.core.security import Staff, require_staff
from app.models.user import User
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_writes(request: Request) -> None:
    """Fixed-window limiter per IP. Fails open if Redis is unavailable."""
    client = get_redis()
    if client is None:
        return
    key = f"ratelimit:write:{client_ip(request)}"
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 60)
    except Exception:
        logger.warning("rate limiter unavailable, allowing request", exc_info=True)
        return
    if count > settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="Too many reports. Please try again in a minute.",
        )


async def rate_limit_auth(request: Request) -> None:
    """Slows password guessing and mass sign-ups with a per-IP fixed window. Fails open
    if Redis is down (password hashing is itself slow, which also limits guessing)."""
    client = get_redis()
    if client is None:
        return
    key = f"ratelimit:auth:{client_ip(request)}"
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 60)
    except Exception:
        logger.warning("auth rate limiter unavailable, allowing request", exc_info=True)
        return
    if count > settings.AUTH_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a minute and try again.")


async def rate_limit_uploads(user: User = Depends(require_user)) -> None:
    """Per-person cap on photo uploads (each one costs storage and a model run)."""
    await _count_upload(f"ratelimit:upload:{user.id}")


async def rate_limit_staff_uploads(staff: Staff = Depends(require_staff)) -> None:
    """The same cap for staff, who may act through the service API key instead of an account."""
    await _count_upload(f"ratelimit:upload:{staff.user.id if staff.user else 'service-key'}")


async def _count_upload(key: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 60)
    except Exception:
        logger.warning("upload rate limiter unavailable, allowing request", exc_info=True)
        return
    if count > settings.UPLOAD_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many uploads. Please wait a minute and try again.")
