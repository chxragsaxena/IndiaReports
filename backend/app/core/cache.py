"""Shared JSON response cache with single-flight.

Hot read endpoints (clusters, pins, dashboard) are identical for many users. Two
problems appear at scale and are handled here:

* Stampede: when a popular key expires, every concurrent request would recompute it.
  Only one does (a Redis lock across processes, an in-process lock within one); the
  rest wait briefly and read the result.
* Cost on hits: the cached value is the finished JSON text, so a hit is one Redis GET
  and no serialisation or validation.

Redis being down or unset never breaks a request: the in-process cache and lock take
over, and the value is simply recomputed per process.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import orjson

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 15
WAIT_FOR_PEER_SECONDS = 3.0
POLL_SECONDS = 0.05
LOCAL_MAX_KEYS = 5000

_local: dict[str, tuple[float, str]] = {}
_inflight: dict[str, list] = {}  # key -> [asyncio.Lock, waiters]


def _local_get(key: str) -> str | None:
    entry = _local.get(key)
    if entry is None:
        return None
    if entry[0] < time.monotonic():
        _local.pop(key, None)
        return None
    return entry[1]


def _local_set(key: str, value: str, ttl: int) -> None:
    if len(_local) >= LOCAL_MAX_KEYS:
        _local.clear()  # bounded: keys come from request parameters
    _local[key] = (time.monotonic() + ttl, value)


async def _read(key: str) -> str | None:
    client = get_redis()
    if client is not None:
        try:
            value = await client.get(key)
            if value is not None:
                return value
        except Exception:
            logger.warning("cache read failed for %s", key, exc_info=True)
    return _local_get(key)


async def _write(key: str, value: str, ttl: int) -> None:
    _local_set(key, value, ttl)
    client = get_redis()
    if client is not None:
        try:
            await client.set(key, value, ex=ttl)
        except Exception:
            logger.warning("cache write failed for %s", key, exc_info=True)


async def cached_json(key: str, ttl: int, compute: Callable[[], Awaitable[Any]]) -> str:
    """Return the JSON text for `key`, computing it at most once per TTL window."""
    hit = await _read(key)
    if hit is not None:
        return hit

    slot = _inflight.setdefault(key, [asyncio.Lock(), 0])
    slot[1] += 1
    try:
        async with slot[0]:
            hit = await _read(key)  # another coroutine here may have filled it
            if hit is not None:
                return hit
            return await _compute_once(key, ttl, compute)
    finally:
        slot[1] -= 1
        if slot[1] == 0:
            _inflight.pop(key, None)


async def _compute_once(key: str, ttl: int, compute: Callable[[], Awaitable[Any]]) -> str:
    client = get_redis()
    lock_key = f"lock:{key}"
    holds_lock = False

    if client is not None:
        try:
            holds_lock = bool(await client.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS))
        except Exception:
            holds_lock = True  # Redis trouble: do not block, just compute

        if not holds_lock:
            # Another process is computing this key: wait for its result.
            deadline = time.monotonic() + WAIT_FOR_PEER_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_SECONDS)
                hit = await _read(key)
                if hit is not None:
                    return hit

    try:
        value = orjson.dumps(await compute()).decode()
        await _write(key, value, ttl)
        return value
    finally:
        if client is not None and holds_lock:
            try:
                await client.delete(lock_key)
            except Exception:
                pass


def clear_local_cache() -> None:
    """Drop the in-process cache (tests, and operations that must not serve stale data)."""
    _local.clear()
