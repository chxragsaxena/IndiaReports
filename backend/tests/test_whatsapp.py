"""Reporting through WhatsApp (Twilio): the signature check, the conversation, voice notes, limits."""

import base64
import hashlib
import hmac
import re

import pytest
from sqlalchemy import text

from app.api.v1.endpoints import whatsapp
from app.core.config import settings
from app.core.redis import get_redis
from app.db.session import engine

URL = "https://api.example/api/v1/whatsapp/webhook"
TOKEN = "twilio-test-token"
PHONE = "whatsapp:+919800000001"
DELHI = {"Latitude": "28.6315", "Longitude": "77.2167"}
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 200


@pytest.fixture(autouse=True)
def whatsapp_on(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", None)
    monkeypatch.setattr(settings, "WHATSAPP_WEBHOOK_URL", URL)
    monkeypatch.setattr(settings, "WHATSAPP_GEOCODE", False)  # no network in tests
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example")


def sign(params: dict, token: str = TOKEN, url: str = URL) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


async def send(client, sender: str = PHONE, **fields) -> str:
    """One incoming WhatsApp message; returns the reply text."""
    form = {"From": sender, "To": "whatsapp:+14155238886", "Body": "", "NumMedia": "0"} | fields
    r = await client.post("/api/v1/whatsapp/webhook", data=form, headers={"X-Twilio-Signature": sign(form)})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/xml")
    found = re.search(r"<Message>(.*)</Message>", r.text, re.S)
    assert found, r.text
    return found.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


async def reports():
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT * FROM reports ORDER BY created_at"))).mappings().all()


# ---- who may call ---------------------------------------------------------------------------


def test_the_signature_matches_what_twilios_own_library_computes():
    # Computed with twilio.request_validator.RequestValidator("twilio-test-token").compute_signature(...).
    params = {"From": "whatsapp:+919800000001", "To": "whatsapp:+14155238886", "Body": "Big pothole & more", "NumMedia": "0",
              "Latitude": "28.6315", "Longitude": "77.2167"}
    signature = "dZovoVgG//NBhdojzlQBsiHlKEc="
    assert whatsapp.valid_signature(URL, params, signature, TOKEN)
    assert not whatsapp.valid_signature(URL, params, signature, "wrong-token")
    assert not whatsapp.valid_signature(URL, params | {"Body": "Something else"}, signature, TOKEN)
    assert not whatsapp.valid_signature(URL + "?x=1", params, signature, TOKEN)
    assert not whatsapp.valid_signature(URL, params, None, TOKEN)


async def test_it_is_off_until_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", None)
    r = await client.post("/api/v1/whatsapp/webhook", data={"From": PHONE, "Body": "hi"})
    assert r.status_code == 503


async def test_a_request_without_a_valid_signature_is_refused(client):
    form = {"From": PHONE, "Body": "Pothole", **DELHI}
    assert (await client.post("/api/v1/whatsapp/webhook", data=form)).status_code == 403
    assert (await client.post("/api/v1/whatsapp/webhook", data=form, headers={"X-Twilio-Signature": "AAAA"})).status_code == 403
    forged = {"X-Twilio-Signature": sign(form, token="someone-elses-token")}
    assert (await client.post("/api/v1/whatsapp/webhook", data=form, headers=forged)).status_code == 403
    assert await reports() == []


# ---- the conversation -------------------------------------------------------------------------


async def test_hello_explains_what_to_send(client):
    reply = await send(client, Body="Hi")
    assert "Location" in reply and "CANCEL" in reply
    assert await reports() == []


async def test_a_description_then_a_location_files_an_anonymous_report(client):
    first = await send(client, Body="Big pothole outside the school gate on Main Road")
    assert "location" in first.lower()
    assert await reports() == []  # not filed until both parts are here

    reply = await send(client, **DELHI)
    (report,) = await reports()
    assert report["title"] == "Big pothole outside the school gate on Main Road"
    assert report["description"] == "Big pothole outside the school gate on Main Road"
    assert report["category"] == "Other" and report["reporter_id"] is None
    assert (report["latitude"], report["longitude"]) == (28.6315, 77.2167)
    assert f"Reference: {str(report['id'])[:8].upper()}" in reply
    assert f"https://app.example/?report={report['id']}" in reply


async def test_a_location_then_a_description_works_too(client):
    assert "describe" in (await send(client, **DELHI)).lower()
    reply = await send(client, Body="Garbage has not been collected for a week")
    (report,) = await reports()
    assert report["description"] == "Garbage has not been collected for a week" and "filed" in reply


async def test_a_shared_address_is_kept(client):
    await send(client, Body="Street light is broken here", **DELHI, Address="Balraj Khanna Marg, West Patel Nagar")
    (report,) = await reports()
    assert report["address"] == "Balraj Khanna Marg, West Patel Nagar"


async def test_a_report_is_routed_like_any_other(client):
    from tests.test_assignment import ADMIN, make_area, square

    area = await make_area(client, "Central Delhi ward", square(77.0, 28.4, 77.4, 28.8))
    await client.post("/api/v1/admin/officers", json={"name": "Ravi (Delhi)", "role": "officer", "area_id": area}, headers=ADMIN)
    reply = await send(client, Body="Water pipe leaking on the road", **DELHI)
    await send(client, **DELHI)
    (report,) = await reports()
    assert report["assigned_officer_id"] is not None and report["area_id"] is not None
    assert "Ravi (Delhi)" in reply or "Ravi (Delhi)" in await send(client, Body="Another leaking pipe here", **DELHI)


async def test_a_place_outside_india_is_refused(client):
    reply = await send(client, Body="Pothole on the road", Latitude="51.5", Longitude="-0.12")
    assert "India" in reply and await reports() == []


async def test_text_that_is_too_short_is_not_taken(client):
    assert "few words" in await send(client, Body="ok")
    assert await reports() == []


async def test_cancel_forgets_the_half_finished_report(client):
    await send(client, Body="A pothole near the bus stop")
    assert "Cancelled" in await send(client, Body="cancel")
    await send(client, **DELHI)  # the old description is gone, so this alone files nothing
    assert await reports() == []


async def test_conversations_are_kept_apart_per_phone(client):
    await send(client, sender="whatsapp:+919800000001", Body="Pothole by the temple on the main road")
    await send(client, sender="whatsapp:+919800000002", **DELHI)
    assert await reports() == []  # two different people, neither has both parts
    await send(client, sender="whatsapp:+919800000001", **DELHI)
    assert len(await reports()) == 1


async def test_the_phone_number_is_never_stored(client):
    await send(client, Body="A pothole near the bus stop on the road", **DELHI)
    async with engine.connect() as conn:
        dump = (await conn.execute(text("SELECT row_to_json(r)::text FROM reports r"))).scalar_one()
        events = " ".join(r[0] for r in (await conn.execute(text("SELECT payload::text FROM outbox_events"))).all())
    redis = get_redis()
    keys = " ".join(await redis.keys("wa:*"))
    for place in (dump, events, keys):
        assert "919800000001" not in place


async def test_the_daily_limit_applies_per_number(client, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_REPORTS_PER_DAY", 1)
    await send(client, Body="First pothole on the main road", **DELHI)
    reply = await send(client, Body="Second pothole on the main road", **DELHI)
    assert "limit" in reply and len(await reports()) == 1
    await send(client, sender="whatsapp:+919800000002", Body="Another number can still report a pothole", **DELHI)
    assert len(await reports()) == 2


async def test_the_reply_is_escaped_so_it_cannot_break_the_xml(client):
    reply = await send(client, Body="<b>Pothole</b> & more near the bus stop", **DELHI)
    assert "filed" in reply
    (report,) = await reports()
    assert report["description"] == "<b>Pothole</b> & more near the bus stop"  # stored as text, not interpreted


# ---- voice notes ---------------------------------------------------------------------------------


def voice_fields():
    return {"NumMedia": "1", "MediaContentType0": "audio/ogg", "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1"}


async def test_a_voice_note_with_a_location_files_a_report_for_transcription(client, photo_store, monkeypatch):
    async def fake_fetch(url):
        return b"OggS" + b"\x00" * 200

    monkeypatch.setattr(whatsapp, "_fetch_voice", fake_fetch)
    await send(client, **voice_fields())
    reply = await send(client, **DELHI)
    (report,) = await reports()
    assert report["description"] == "Voice report. The spoken description is being transcribed."
    assert "voice note" in reply
    async with engine.connect() as conn:
        note = (await conn.execute(text("SELECT * FROM report_voice_notes"))).mappings().one()
        event = (await conn.execute(text("SELECT payload FROM outbox_events WHERE event_type = 'VoiceNoteUploaded'"))).scalar_one()
    assert note["uploader_id"] is None and note["content_type"] == "audio/ogg" and note["status"] == "pending"
    assert event["voice_id"] == str(note["id"]) and event["language"] is None
    assert note["storage_key"] in photo_store.objects


async def test_text_wins_over_a_voice_note_for_the_description(client, photo_store, monkeypatch):
    async def fake_fetch(url):
        return WEBM

    monkeypatch.setattr(whatsapp, "_fetch_voice", fake_fetch)
    await send(client, Body="Deep pothole at the crossing near the market", **voice_fields())
    await send(client, **DELHI)
    (report,) = await reports()
    assert report["description"] == "Deep pothole at the crossing near the market"


async def test_an_unreadable_voice_note_without_text_files_nothing(client, photo_store, monkeypatch):
    async def fake_fetch(url):
        return None

    monkeypatch.setattr(whatsapp, "_fetch_voice", fake_fetch)
    await send(client, **voice_fields())
    reply = await send(client, **DELHI)
    assert "could not read your voice note" in reply and await reports() == []


async def test_a_bad_voice_file_is_refused_not_stored(client, photo_store, monkeypatch):
    async def fake_fetch(url):
        return b"MZ\x90\x00" + b"\x00" * 100  # not audio

    monkeypatch.setattr(whatsapp, "_fetch_voice", fake_fetch)
    await send(client, **voice_fields())
    reply = await send(client, **DELHI)
    assert "could not read" in reply and await reports() == [] and photo_store.objects == {}


async def test_only_twilios_own_https_addresses_are_downloaded():
    assert await whatsapp._fetch_voice("http://api.twilio.com/x") is None  # not https
    assert await whatsapp._fetch_voice("https://evil.example/x") is None
    assert await whatsapp._fetch_voice("https://api.twilio.com.evil.example/x") is None
    assert await whatsapp._fetch_voice("") is None
