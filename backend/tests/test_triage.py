import json
import os

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from tests.conftest import sample_report

API_KEY = {"X-API-Key": os.environ["ADMIN_API_KEY"]}
INTERNAL = {"X-Internal-Key": "internal-test-key"}

TRIAGE = {
    "language": "Hindi", "title_en": "Deep pothole", "description_en": "A deep pothole near the school gate.",
    "suggested_category": "Road", "category_matches_report": True, "urgency": "high", "is_spam": False,
    "spam_reason": "", "summary": "Deep pothole near a school.", "confidence": 0.9,
    "provider": "fake", "model": "fake-text",
}


@pytest.fixture(autouse=True)
def internal_key(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "internal-test-key")


async def new_report(client, **overrides):
    r = await client.post("/api/v1/reports/", json=sample_report(**overrides))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def outbox(kind):
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT payload FROM outbox_events WHERE event_type = :t"), {"t": kind})).all()
    return [r.payload for r in rows]


async def send(client, report_id, triage=None, status="done", headers=INTERNAL):
    return await client.post(
        f"/api/v1/internal/reports/{report_id}/triage", headers=headers,
        json={"status": status, "triage": TRIAGE if triage is None else triage},
    )


async def test_a_new_report_queues_its_text_for_triage_without_leaking_it_to_the_live_map(client):
    report_id = await new_report(client, description="Very deep, near the school gate")
    (queued,) = await outbox("ReportTriageRequested")
    assert queued["report_id"] == report_id and queued["description"] == "Very deep, near the school gate"
    (created,) = await outbox("ReportCreated")
    assert "description" not in created


async def test_triage_is_stored_and_staff_see_it(client):
    report_id = await new_report(client)
    assert (await send(client, report_id)).status_code == 200

    detail = (await client.get(f"/api/v1/admin/reports/{report_id}", headers=API_KEY)).json()
    assert detail["triage"]["language"] == "Hindi" and detail["triage"]["description_en"].startswith("A deep pothole")

    row = (await client.get("/api/v1/admin/reports", headers=API_KEY)).json()["items"][0]
    assert row["ai_urgency"] == "high" and row["language"] == "Hindi" and row["ai_spam"] is False


async def test_english_reports_show_no_language_badge_and_spam_is_flagged(client):
    report_id = await new_report(client)
    await send(client, report_id, TRIAGE | {"language": "English", "is_spam": True, "spam_reason": "An advert."})
    row = (await client.get("/api/v1/admin/reports", headers=API_KEY)).json()["items"][0]
    assert row["language"] is None and row["ai_spam"] is True


async def test_triage_never_reaches_the_public(client):
    report_id = await new_report(client)
    await send(client, report_id)
    for url in (f"/api/v1/reports/{report_id}", "/api/v1/reports/"):
        body = (await client.get(url)).text
        assert "triage" not in body and "description_en" not in body


async def test_a_second_result_does_not_overwrite_the_first(client):
    report_id = await new_report(client)
    await send(client, report_id)
    again = await send(client, report_id, TRIAGE | {"urgency": "low"})
    assert again.json()["ignored"] is True
    detail = (await client.get(f"/api/v1/admin/reports/{report_id}", headers=API_KEY)).json()
    assert detail["triage"]["urgency"] == "high"


async def test_the_triage_endpoint_needs_the_internal_key_and_valid_data(client, monkeypatch):
    report_id = await new_report(client)
    assert (await send(client, report_id, headers={})).status_code == 401
    assert (await send(client, report_id, headers=API_KEY)).status_code == 401
    assert (await send(client, report_id, TRIAGE | {"urgency": "apocalyptic"})).status_code == 422
    assert (await send(client, "00000000-0000-0000-0000-000000000000")).status_code == 404
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    assert (await send(client, report_id)).status_code == 503


async def test_model_output_is_bounded_and_unknown_fields_are_dropped(client):
    report_id = await new_report(client)
    await send(client, report_id, TRIAGE | {"summary": "x" * 5000, "confidence": 99, "surprise": "<script>"})
    triage = (await client.get(f"/api/v1/admin/reports/{report_id}", headers=API_KEY)).json()["triage"]
    assert len(triage["summary"]) == 300 and triage["confidence"] == 1.0 and "surprise" not in triage
    assert "<script>" not in json.dumps(triage)


async def test_a_failed_triage_changes_nothing(client):
    report_id = await new_report(client)
    r = await client.post(f"/api/v1/internal/reports/{report_id}/triage", headers=INTERNAL, json={"status": "failed", "error": "busy"})
    assert r.status_code == 200
    detail = (await client.get(f"/api/v1/admin/reports/{report_id}", headers=API_KEY)).json()
    assert detail["triage"] is None
