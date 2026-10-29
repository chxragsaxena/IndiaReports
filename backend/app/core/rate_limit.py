import logging

from fastapi import HTTPException, Request

from app.core.config import settings
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
