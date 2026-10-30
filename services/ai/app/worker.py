"""Consumes events from the report-service and sends back what the open-weight models made of them.

  ReportImageUploaded   -> the vision model looks at the photo      -> /internal/images/{id}/analysis
  ReportTriageRequested -> a small text model reads the report text -> /internal/reports/{id}/triage
  FixPhotoUploaded      -> the vision model compares before and after -> /internal/images/{id}/verification

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
from app.analysis.triage import TextContext
from app.analysis.verifier import FixContext
from app.config import settings
from app.reporting import Rejected, ReportServiceClient, Unavailable
from app.store import PhotoStore

logger = logging.getLogger(__name__)

IMAGE_EVENT = "ReportImageUploaded"
EVENT_TYPE = IMAGE_EVENT  # kept for older imports
TRIAGE_EVENT = "ReportTriageRequested"
FIX_EVENT = "FixPhotoUploaded"
RETRY_BACKOFF = (60, 300, 1800)  # seconds to wait before attempt 2, 3, ...
CONSUMER = f"{socket.gethostname()}-{os.getpid()}"


async def ensure_group(redis) -> None:
    try:
        # From the start of the stream, so work queued while this service was down is not missed.
        await redis.xgroup_create(settings.EVENT_STREAM, settings.CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as e:  # BUSYGROUP: it already exists
        if "BUSYGROUP" not in str(e):
            raise


async def _within_daily_cap(redis, name: str, cap: int) -> bool:
    key = f"ai:{name}:{datetime.now(timezone.utc):%Y%m%d}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 2 * 24 * 3600)
    return count <= cap


async def handle(
    fields: dict, attempts: int, redis, analyzer: Analyzer | None, store: PhotoStore | None,
    reporter: ReportServiceClient, triager=None, verifier=None,
) -> bool:
    """Process one message. True means it is finished (acknowledge it); False means try again later."""
    kind = fields.get("type")
    if kind not in (IMAGE_EVENT, TRIAGE_EVENT, FIX_EVENT):
        return True
    try:
        data = json.loads(fields["data"])
        subject = data["report_id"] if kind == TRIAGE_EVENT else data["image_id"]
    except (KeyError, ValueError, TypeError):
        logger.warning("dropping a malformed %s event", kind)
        return True

    if kind == IMAGE_EVENT:
        if analyzer is None or store is None:
            return True  # photo analysis is off: the photo simply keeps waiting
        send, cap_name, cap = reporter.send_analysis, "analyses", settings.ANALYSIS_MAX_PER_DAY
    elif kind == FIX_EVENT:
        if verifier is None or store is None:
            return True  # fix verification is off
        send, cap_name, cap = reporter.send_verification, "verifications", settings.VERIFY_MAX_PER_DAY
    else:
        if triager is None:
            return True  # text triage is off
        send, cap_name, cap = reporter.send_triage, "triage", settings.TRIAGE_MAX_PER_DAY

    async def fail(error: str) -> bool:
        try:
            await send(subject, {"status": "failed", "error": error[:500], "attempts": attempts})
        except Rejected as e:
            logger.warning("result for %s refused: %s", subject, e)
        except Unavailable as e:
            logger.warning("could not report failure for %s: %s", subject, e)
            return False
        return True

    if not await _within_daily_cap(redis, cap_name, cap):
        return await fail("The daily analysis limit was reached.")

    try:
        if kind == IMAGE_EVENT:
            photo = await store.get(data["storage_key"])
            findings = await analyzer.analyze(
                photo,
                data.get("content_type", "image/jpeg"),
                ReportContext(data.get("title", ""), data.get("description", ""), data.get("category", "Other")),
            )
            body = {
                "status": "done", "severity": findings.severity, "analysis": findings.model_dump(),
                "provider": analyzer.provider, "model": analyzer.model, "attempts": attempts,
            }
        elif kind == FIX_EVENT:
            after = await store.get(data["storage_key"])
            before = await store.get(data["before_key"]) if data.get("before_key") else None
            verdict = await verifier.verify(
                after, data.get("content_type", "image/jpeg"),
                FixContext(data.get("title", ""), data.get("description", ""), data.get("category", "Other")),
                before, data.get("before_content_type") or "image/jpeg",
            )
            body = {
                "status": "done", "verification": verdict.model_dump(),
                "provider": verifier.provider, "model": verifier.model, "attempts": attempts,
            }
        else:
            triage = await triager.triage(TextContext(data.get("title", ""), data.get("description", ""), data.get("category", "Other")))
            body = {
                "status": "done", "attempts": attempts,
                "triage": triage.model_dump() | {"provider": triager.provider, "model": triager.model},
            }
    except AnalysisError as e:
        give_up = (not e.retryable) or attempts >= settings.ANALYSIS_MAX_ATTEMPTS
        logger.warning("%s of %s failed (attempt %d, %s): %s", kind, subject, attempts, "giving up" if give_up else "will retry", e)
        return await fail(str(e)) if give_up else False
    except Exception as e:  # storage hiccup or a bug: never crash the loop
        logger.exception("unexpected error handling %s %s", kind, subject)
        if attempts >= settings.ANALYSIS_MAX_ATTEMPTS:
            return await fail(f"Unexpected error: {e.__class__.__name__}")
        return False

    try:
        await send(subject, body)
    except Rejected as e:
        logger.warning("result for %s refused: %s", subject, e)
        return True
    except Unavailable as e:
        logger.warning("result for %s not delivered, will retry: %s", subject, e)
        return False
    return True


async def _run_batch(entries, attempts_of, redis, analyzer, store, reporter, triager, verifier=None) -> None:
    async def one(msg_id, fields):
        try:
            finished = await handle(fields, attempts_of(msg_id), redis, analyzer, store, reporter, triager, verifier)
        except Exception:
            logger.exception("handler crashed on %s", msg_id)
            finished = False
        if finished:
            await redis.xack(settings.EVENT_STREAM, settings.CONSUMER_GROUP, msg_id)

    await asyncio.gather(*(one(m, f) for m, f in entries))


async def process_once(
    redis, analyzer: Analyzer | None, store: PhotoStore | None, reporter: ReportServiceClient,
    block_ms: int = 2000, triager=None, verifier=None,
) -> int:
    """Handle new messages, then any failed ones whose delay has passed. Returns how many were handled."""
    handled = 0
    just_read: set[str] = set()

    reply = await redis.xreadgroup(
        settings.CONSUMER_GROUP, CONSUMER, {settings.EVENT_STREAM: ">"},
        count=max(1, settings.ANALYSIS_CONCURRENCY) * 10, block=block_ms,
    )
    for _stream, entries in reply or []:
        just_read.update(m for m, _ in entries)
        await _run_batch(entries, lambda _id: 1, redis, analyzer, store, reporter, triager, verifier)
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
        await _run_batch(claimed, lambda _id: due.get(_id, 2), redis, analyzer, store, reporter, triager, verifier)
        handled += len(claimed)
    return handled


async def run_worker(
    stop: asyncio.Event, redis, analyzer: Analyzer | None, store: PhotoStore | None,
    reporter: ReportServiceClient, triager=None, verifier=None,
) -> None:
    """Background loop. Errors only delay work; they never raise."""
    logger.info(
        "ai worker on: photos=%s text=%s fixes=%s",
        f"{analyzer.provider}/{analyzer.model}" if analyzer else "off",
        f"{triager.provider}/{triager.model}" if triager else "off",
        f"{verifier.provider}/{verifier.model}" if verifier else "off",
    )
    ready = False
    while not stop.is_set():
        try:
            if not ready:
                await ensure_group(redis)
                ready = True
            await process_once(redis, analyzer, store, reporter, triager=triager, verifier=verifier)
        except Exception:
            logger.warning("worker loop error, retrying", exc_info=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
