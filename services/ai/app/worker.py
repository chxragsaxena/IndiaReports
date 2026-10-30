"""Consumes ReportImageUploaded events and sends back the vision model's findings.

The work queue is the Redis stream itself (a consumer group), so this service needs no database:
a message stays "pending" until it is acknowledged, a crashed worker's messages are picked up
again, and a failed attempt is simply not acknowledged and is redelivered after a growing delay.
"""

import asyncio
import json
import logging
import os
import socket
from datetime import datetime, timezone

from app.analysis.analyzer import Analyzer, AnalysisError, ReportContext
from app.config import settings
from app.reporting import Rejected, ReportServiceClient, Unavailable
from app.store import PhotoStore

logger = logging.getLogger(__name__)

EVENT_TYPE = "ReportImageUploaded"
RETRY_BACKOFF = (60, 300, 1800)  # seconds to wait before attempt 2, 3, ...
CONSUMER = f"{socket.gethostname()}-{os.getpid()}"


async def ensure_group(redis) -> None:
    try:
        # From the start of the stream, so photos uploaded while this service was down are not missed.
        await redis.xgroup_create(settings.EVENT_STREAM, settings.CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as e:  # BUSYGROUP: it already exists
        if "BUSYGROUP" not in str(e):
            raise


async def _within_daily_cap(redis) -> bool:
    key = f"ai:analyses:{datetime.now(timezone.utc):%Y%m%d}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 2 * 24 * 3600)
    return count <= settings.ANALYSIS_MAX_PER_DAY


async def handle(fields: dict, attempts: int, redis, analyzer: Analyzer, store: PhotoStore, reporter: ReportServiceClient) -> bool:
    """Process one message. True means it is finished (acknowledge it); False means try again later."""
    if fields.get("type") != EVENT_TYPE:
        return True
    try:
        data = json.loads(fields["data"])
        image_id = data["image_id"]
    except (KeyError, ValueError, TypeError):
        logger.warning("dropping a malformed %s event", EVENT_TYPE)
        return True

    async def fail(error: str) -> bool:
        try:
            await reporter.send_analysis(image_id, {"status": "failed", "error": error[:500], "attempts": attempts})
        except Rejected as e:
            logger.warning("result for %s refused: %s", image_id, e)
        except Unavailable as e:
            logger.warning("could not report failure for %s: %s", image_id, e)
            return False
        return True

    if not await _within_daily_cap(redis):
        return await fail("The daily analysis limit was reached.")

    try:
        photo = await store.get(data["storage_key"])
        findings = await analyzer.analyze(
            photo,
            data.get("content_type", "image/jpeg"),
            ReportContext(data.get("title", ""), data.get("description", ""), data.get("category", "Other")),
        )
    except AnalysisError as e:
        give_up = (not e.retryable) or attempts >= settings.ANALYSIS_MAX_ATTEMPTS
        logger.warning("analysis of %s failed (attempt %d, %s): %s", image_id, attempts, "giving up" if give_up else "will retry", e)
        return await fail(str(e)) if give_up else False
    except Exception as e:  # storage hiccup or a bug: never crash the loop
        logger.exception("unexpected error analysing %s", image_id)
        if attempts >= settings.ANALYSIS_MAX_ATTEMPTS:
            return await fail(f"Unexpected error: {e.__class__.__name__}")
        return False

    try:
        await reporter.send_analysis(image_id, {
            "status": "done",
            "severity": findings.severity,
            "analysis": findings.model_dump(),
            "provider": analyzer.provider,
            "model": analyzer.model,
            "attempts": attempts,
        })
    except Rejected as e:
        logger.warning("result for %s refused: %s", image_id, e)
        return True
    except Unavailable as e:
        logger.warning("result for %s not delivered, will retry: %s", image_id, e)
        return False
    return True


async def _run_batch(entries, attempts_of, redis, analyzer, store, reporter) -> None:
    async def one(msg_id, fields):
        try:
            finished = await handle(fields, attempts_of(msg_id), redis, analyzer, store, reporter)
        except Exception:
            logger.exception("handler crashed on %s", msg_id)
            finished = False
        if finished:
            await redis.xack(settings.EVENT_STREAM, settings.CONSUMER_GROUP, msg_id)

    await asyncio.gather(*(one(m, f) for m, f in entries))


async def process_once(redis, analyzer: Analyzer, store: PhotoStore, reporter: ReportServiceClient, block_ms: int = 2000) -> int:
    """Handle new messages, then any failed ones whose delay has passed. Returns how many were handled."""
    handled = 0
    just_read: set[str] = set()

    reply = await redis.xreadgroup(
        settings.CONSUMER_GROUP, CONSUMER, {settings.EVENT_STREAM: ">"},
        count=max(1, settings.ANALYSIS_CONCURRENCY) * 10, block=block_ms,
    )
    for _stream, entries in reply or []:
        just_read.update(m for m, _ in entries)
        await _run_batch(entries, lambda _id: 1, redis, analyzer, store, reporter)
        handled += len(entries)

    # Messages delivered earlier and never acknowledged: retry them once their back-off has passed.
    pending = await redis.xpending_range(
        settings.EVENT_STREAM, settings.CONSUMER_GROUP, min="-", max="+", count=20, idle=RETRY_BACKOFF[0] * 1000
    )
    due: dict[str, int] = {}
    for p in pending:
        if p["message_id"] in just_read:
            continue  # tried a moment ago in this pass
        wait = RETRY_BACKOFF[min(p["times_delivered"] - 1, len(RETRY_BACKOFF) - 1)]
        if p["time_since_delivered"] >= wait * 1000:
            due[p["message_id"]] = p["times_delivered"] + 1  # the claim below is another delivery
    if due:
        claimed = await redis.xclaim(
            settings.EVENT_STREAM, settings.CONSUMER_GROUP, CONSUMER,
            min_idle_time=RETRY_BACKOFF[0] * 1000, message_ids=list(due),
        )
        await _run_batch(claimed, lambda _id: due.get(_id, 2), redis, analyzer, store, reporter)
        handled += len(claimed)
    return handled


async def run_worker(stop: asyncio.Event, redis, analyzer: Analyzer, store: PhotoStore, reporter: ReportServiceClient) -> None:
    """Background loop. Errors only delay work; they never raise."""
    logger.info("photo analysis on: provider=%s model=%s", analyzer.provider, analyzer.model)
    ready = False
    while not stop.is_set():
        try:
            if not ready:
                await ensure_group(redis)
                ready = True
            await process_once(redis, analyzer, store, reporter)
        except Exception:
            logger.warning("worker loop error, retrying", exc_info=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
