import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis | None:
    """Shared Redis client, or None when REDIS_URL is not configured."""
    global _client
    if not settings.REDIS_URL:
        return None
    if _client is None:
        # A bounded pool that makes callers wait briefly for a connection, instead of
        # opening a new one per concurrent request (which times out under load).
        pool = aioredis.BlockingConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            timeout=2,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        _client = aioredis.Redis(connection_pool=pool)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def cache_get(key: str) -> Any | None:
    """Cache failures are never fatal: a miss is returned instead."""
    client = get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("cache_get failed for %s", key, exc_info=True)
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value), ex=ttl)
    except Exception:
        logger.warning("cache_set failed for %s", key, exc_info=True)
