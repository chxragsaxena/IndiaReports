import json
import os
import uuid

import pytest
import redis.asyncio as aioredis

from app import worker
from app.analysis.analyzer import AnalysisError
from app.analysis.schema import Findings
from app.analysis.triage import Triage
from app.config import settings
from app.reporting import Rejected, Unavailable

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="needs Redis (TEST_REDIS_URL)")

IMAGE = str(uuid.uuid4())


def findings(severity="medium"):
    return Findings(
        summary="A pothole.", issue_visible=True, suggested_category="Road", category_matches_report=True,
        severity=severity, hazards=[], recommended_action="Fix it.", image_quality="good", flags=[], confidence=0.8,
    )


class FakeAnalyzer:
    provider, model = "fake", "fake-1"

    def __init__(self, error=None):
        self.error, self.calls = error, 0

    async def analyze(self, image, media_type, context):
        self.calls += 1
        if self.error:
            raise self.error
        return findings()


class FakeStore:
    async def get(self, key):
        return b"jpeg-bytes"


class FakeReporter:
    def __init__(self, error=None):
        self.error, self.sent = error, []

    async def send_analysis(self, image_id, body):
        if self.error:
            raise self.error
        self.sent.append((image_id, body))

    send_triage = send_verification = send_analysis


@pytest.fixture
async def redis(monkeypatch):
    client = aioredis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    stream = f"test.events.{uuid.uuid4().hex}"
    monkeypatch.setattr(settings, "EVENT_STREAM", stream)
    monkeypatch.setattr(worker, "RETRY_BACKOFF", (0,))  # retry straight away instead of waiting minutes
    await worker.ensure_group(client)
    yield client
    await client.delete(stream)
    await client.aclose()


async def publish(redis, kind="ReportImageUploaded", **data):
    payload = {"image_id": IMAGE, "report_id": str(uuid.uuid4()), "storage_key": "reports/x/y.jpg",
               "content_type": "image/jpeg", "title": "Pothole", "description": "Deep", "category": "Road"} | data
    await redis.xadd(settings.EVENT_STREAM, {"event_id": "1", "type": kind, "data": json.dumps(payload)})


async def pending(redis):
    return (await redis.xpending(settings.EVENT_STREAM, settings.CONSUMER_GROUP))["pending"]


async def run(redis, analyzer, reporter):
    return await worker.process_once(redis, analyzer, FakeStore(), reporter, block_ms=50)


async def test_an_uploaded_photo_is_analysed_and_the_result_sent(redis):
    await publish(redis)
    analyzer, reporter = FakeAnalyzer(), FakeReporter()
    assert await run(redis, analyzer, reporter) == 1
    (image_id, body), = reporter.sent
    assert image_id == IMAGE and body["status"] == "done" and body["severity"] == "medium"
    assert body["provider"] == "fake" and body["analysis"]["summary"] == "A pothole." and body["attempts"] == 1
    assert await pending(redis) == 0


async def test_other_events_are_ignored_and_acknowledged(redis):
    await publish(redis, kind="ReportCreated")
    analyzer, reporter = FakeAnalyzer(), FakeReporter()
    await run(redis, analyzer, reporter)
    assert analyzer.calls == 0 and reporter.sent == [] and await pending(redis) == 0


async def test_a_malformed_event_is_dropped_not_retried_forever(redis):
    await redis.xadd(settings.EVENT_STREAM, {"event_id": "1", "type": "ReportImageUploaded", "data": "{not json"})
    await run(redis, FakeAnalyzer(), FakeReporter())
    assert await pending(redis) == 0


async def test_a_temporary_failure_is_retried_then_given_up_on(redis, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_ATTEMPTS", 3)
    await publish(redis)
    analyzer, reporter = FakeAnalyzer(error=AnalysisError("model busy", retryable=True)), FakeReporter()

    await run(redis, analyzer, reporter)  # attempt 1
    assert reporter.sent == [] and await pending(redis) == 1
    await run(redis, analyzer, reporter)  # attempt 2
    assert reporter.sent == [] and await pending(redis) == 1
    await run(redis, analyzer, reporter)  # attempt 3: gives up and says so
    (_, body), = reporter.sent
    assert body["status"] == "failed" and "model busy" in body["error"] and body["attempts"] == 3
    assert analyzer.calls == 3 and await pending(redis) == 0


async def test_a_permanent_failure_is_reported_at_once(redis):
    await publish(redis)
    reporter = FakeReporter()
    await run(redis, FakeAnalyzer(error=AnalysisError("wrong model name", retryable=False)), reporter)
    (_, body), = reporter.sent
    assert body["status"] == "failed" and body["attempts"] == 1 and await pending(redis) == 0


async def test_an_unexpected_error_never_crashes_the_worker(redis):
    await publish(redis)
    reporter = FakeReporter()
    await run(redis, FakeAnalyzer(error=RuntimeError("boom")), reporter)
    assert reporter.sent == [] and await pending(redis) == 1  # kept for another try


async def test_when_the_report_service_is_down_the_result_is_kept_for_later(redis):
    await publish(redis)
    down = FakeReporter(error=Unavailable("report-service answered 503"))
    await run(redis, FakeAnalyzer(), down)
    assert await pending(redis) == 1

    up = FakeReporter()
    await run(redis, FakeAnalyzer(), up)  # delivered on the next pass
    assert len(up.sent) == 1 and up.sent[0][1]["attempts"] == 2 and await pending(redis) == 0


async def test_a_refused_result_is_dropped(redis):
    await publish(redis)
    await run(redis, FakeAnalyzer(), FakeReporter(error=Rejected("report-service refused the result (404)")))
    assert await pending(redis) == 0


async def test_the_daily_cap_stops_analysis(redis, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_PER_DAY", 1)
    key_day = await redis.keys("ai:analyses:*")
    await redis.delete(*key_day) if key_day else None
    await publish(redis, image_id=str(uuid.uuid4()))
    await publish(redis, image_id=str(uuid.uuid4()))
    analyzer, reporter = FakeAnalyzer(), FakeReporter()
    await run(redis, analyzer, reporter)
    statuses = sorted(body["status"] for _, body in reporter.sent)
    assert statuses == ["done", "failed"] and analyzer.calls == 1
    assert "daily" in next(b["error"] for _, b in reporter.sent if b["status"] == "failed")
    await redis.delete(*await redis.keys("ai:analyses:*"))


# ---- text triage --------------------------------------------------------------------------

REPORT = str(uuid.uuid4())


class FakeTriager:
    provider, model = "fake", "fake-text"

    def __init__(self, error=None):
        self.error, self.calls = error, []

    async def triage(self, ctx):
        self.calls.append(ctx)
        if self.error:
            raise self.error
        return Triage(
            language="Hindi", title_en="Deep pothole", description_en="A deep pothole near the school.",
            suggested_category="Road", category_matches_report=True, urgency="high", is_spam=False,
            spam_reason="", summary="Deep pothole near a school.", confidence=0.9,
        )


async def publish_triage(redis, **data):
    payload = {"report_id": REPORT, "title": "गहरा गड्ढा", "description": "स्कूल के पास", "category": "Road"} | data
    await redis.xadd(settings.EVENT_STREAM, {"event_id": "2", "type": "ReportTriageRequested", "data": json.dumps(payload)})


async def test_report_text_is_triaged_and_the_result_sent(redis):
    await publish_triage(redis)
    triager, reporter = FakeTriager(), FakeReporter()
    await worker.process_once(redis, None, None, reporter, block_ms=50, triager=triager)
    (report_id, body), = reporter.sent
    assert report_id == REPORT and body["status"] == "done"
    assert body["triage"]["language"] == "Hindi" and body["triage"]["urgency"] == "high"
    assert body["triage"]["provider"] == "fake" and body["triage"]["model"] == "fake-text"
    assert triager.calls[0].title == "गहरा गड्ढा" and await pending(redis) == 0


async def test_triage_is_skipped_when_no_text_model_is_configured(redis):
    await publish_triage(redis)
    reporter = FakeReporter()
    await worker.process_once(redis, None, None, reporter, block_ms=50, triager=None)
    assert reporter.sent == [] and await pending(redis) == 0


async def test_a_failing_triage_retries_then_is_reported_as_failed(redis, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_ATTEMPTS", 2)
    await publish_triage(redis)
    triager, reporter = FakeTriager(error=AnalysisError("busy", retryable=True)), FakeReporter()
    for _ in range(2):
        await worker.process_once(redis, None, None, reporter, block_ms=50, triager=triager)
    (_, body), = reporter.sent
    assert body["status"] == "failed" and body["attempts"] == 2 and await pending(redis) == 0


async def test_photo_events_are_left_alone_when_only_text_triage_is_on(redis):
    await publish(redis)
    reporter = FakeReporter()
    await worker.process_once(redis, None, None, reporter, block_ms=50, triager=FakeTriager())
    assert reporter.sent == []


# ---- before/after fix verification -------------------------------------------------------


class FakeVerifier:
    provider, model = "fake", "fake-vision"

    def __init__(self, error=None):
        self.error, self.calls = error, []

    async def verify(self, after, after_type, ctx, before=None, before_type="image/jpeg"):
        self.calls.append((after, before))
        if self.error:
            raise self.error
        from app.analysis.verifier import Verification

        return Verification(
            verdict="fixed", same_location=True, compared_with_original=before is not None,
            summary="Filled in.", remaining_issues=[], confidence=0.9,
        )


class KeyedStore:
    async def get(self, key):
        return key.encode()


async def test_a_repair_photo_is_compared_with_the_original_and_the_verdict_sent(redis):
    await publish(redis, kind="FixPhotoUploaded", storage_key="reports/x/fix.jpg", before_key="reports/x/before.jpg")
    verifier, reporter = FakeVerifier(), FakeReporter()
    await worker.process_once(redis, None, KeyedStore(), reporter, block_ms=50, verifier=verifier)
    assert verifier.calls == [(b"reports/x/fix.jpg", b"reports/x/before.jpg")]
    (image_id, body), = reporter.sent
    assert image_id == IMAGE and body["status"] == "done" and body["verification"]["verdict"] == "fixed"
    assert body["provider"] == "fake" and body["verification"]["compared_with_original"] is True
    assert await pending(redis) == 0


async def test_a_repair_photo_with_no_original_is_still_judged(redis):
    await publish(redis, kind="FixPhotoUploaded", storage_key="reports/x/fix.jpg", before_key=None)
    verifier, reporter = FakeVerifier(), FakeReporter()
    await worker.process_once(redis, None, KeyedStore(), reporter, block_ms=50, verifier=verifier)
    assert verifier.calls == [(b"reports/x/fix.jpg", None)]
    assert reporter.sent[0][1]["verification"]["compared_with_original"] is False


async def test_repair_photos_wait_when_verification_is_off(redis):
    await publish(redis, kind="FixPhotoUploaded", before_key=None)
    reporter = FakeReporter()
    await worker.process_once(redis, FakeAnalyzer(), KeyedStore(), reporter, block_ms=50)  # no verifier
    assert reporter.sent == [] and await pending(redis) == 0


async def test_a_failed_verification_is_retried_then_reported(redis, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_ATTEMPTS", 2)
    await publish(redis, kind="FixPhotoUploaded", before_key=None)
    verifier, reporter = FakeVerifier(error=AnalysisError("model busy", retryable=True)), FakeReporter()
    await worker.process_once(redis, None, KeyedStore(), reporter, block_ms=50, verifier=verifier)
    assert reporter.sent == [] and await pending(redis) == 1
    await worker.process_once(redis, None, KeyedStore(), reporter, block_ms=50, verifier=verifier)
    (_, body), = reporter.sent
    assert body["status"] == "failed" and await pending(redis) == 0
