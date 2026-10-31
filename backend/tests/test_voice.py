"""Voice notes: a spoken description, stored like a photo, transcribed by the ai-service."""

import json
import os

import pytest
from sqlalchemy import text

from app.core.audio import VOICE_PLACEHOLDER, AudioRejected, clamp_duration, sniff
from app.core.config import settings
from app.db.session import engine
from tests.conftest import sample_report
from tests.test_images import bearer, citizen, events, report_by

API_KEY = {"X-API-Key": os.environ["ADMIN_API_KEY"]}
INTERNAL = {"X-Internal-Key": "internal-test-key"}

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 200
OGG = b"OggS" + b"\x00" * 200
M4A = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 200
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 200
MP3 = b"ID3\x03" + b"\x00" * 200


@pytest.fixture(autouse=True)
def internal_key(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "internal-test-key")


async def speak(client, report_id, token, data=WEBM, ctype="audio/webm", duration=None):
    return await client.post(
        f"/api/v1/reports/{report_id}/voice",
        files={"file": ("voice.webm", data, ctype)},
        data={"duration_seconds": str(duration)} if duration is not None else {},
        headers=bearer(token),
    )


async def note_row():
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT * FROM report_voice_notes"))).mappings().one()


async def transcript(client, voice_id, body=None, headers=INTERNAL):
    body = body or {"status": "done", "transcript": "There is a deep pothole near the school.", "language": "English",
                    "provider": "fake", "model": "fake-whisper"}
    return await client.post(f"/api/v1/internal/voice/{voice_id}/transcript", json=body, headers=headers)


async def spoken_report(client, description=VOICE_PLACEHOLDER):
    token = await citizen(client)
    report_id = await report_by(client, token, description=description)
    assert (await speak(client, report_id, token, duration=12)).status_code == 201
    return token, report_id


# ---- checking the file ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "data,content_type,extension",
    [(WEBM, "audio/webm", "webm"), (OGG, "audio/ogg", "ogg"), (M4A, "audio/mp4", "m4a"), (WAV, "audio/wav", "wav"), (MP3, "audio/mpeg", "mp3")],
)
def test_browser_audio_formats_are_recognised_by_their_bytes(data, content_type, extension):
    kind = sniff(data)
    assert (kind.content_type, kind.extension) == (content_type, extension)


@pytest.mark.parametrize("data", [b"", b"MZ\x90\x00" + b"\x00" * 100, b"<script>alert(1)</script>", b"\xff\xd8\xff\xe0" + b"\x00" * 100])
def test_things_that_are_not_audio_are_refused(data):
    with pytest.raises(AudioRejected):
        sniff(data)


def test_the_reported_duration_is_only_a_clamped_hint():
    assert clamp_duration(None, 90) is None
    assert clamp_duration(-5, 90) == 0
    assert clamp_duration(10_000, 90) == 90
    assert clamp_duration(42, 90) == 42


# ---- uploading -----------------------------------------------------------------------------


async def test_the_owner_can_attach_a_voice_note_and_the_ai_service_is_told(client, photo_store):
    token, report_id = await spoken_report(client)
    row = await note_row()
    assert row["status"] == "pending" and row["content_type"] == "audio/webm" and row["duration_seconds"] == 12
    assert row["storage_key"] in photo_store.objects and photo_store.objects[row["storage_key"]][1] == "audio/webm"
    (sent,) = await events("VoiceNoteUploaded")
    assert sent["voice_id"] == str(row["id"]) and sent["report_id"] == report_id
    assert sent["storage_key"] == row["storage_key"] and sent["content_type"] == "audio/webm"


async def test_the_event_does_not_carry_the_report_text_or_the_audio(client, photo_store):
    await spoken_report(client)
    (sent,) = await events("VoiceNoteUploaded")
    assert set(sent) == {"voice_id", "report_id", "storage_key", "content_type", "size_bytes"}


async def test_a_voice_note_needs_sign_in_and_ownership(client, photo_store):
    token = await citizen(client)
    report_id = await report_by(client, token)
    anonymous = await client.post(f"/api/v1/reports/{report_id}/voice", files={"file": ("v.webm", WEBM, "audio/webm")})
    assert anonymous.status_code == 401
    other = await citizen(client, "other@example.org")
    assert (await speak(client, report_id, other)).status_code == 404  # same answer as "no such report"


async def test_fake_audio_is_refused_whatever_the_content_type_claims(client, photo_store):
    token = await citizen(client)
    report_id = await report_by(client, token)
    response = await speak(client, report_id, token, data=b"MZ\x90\x00" + b"\x00" * 100, ctype="audio/webm")
    assert response.status_code == 422
    assert photo_store.objects == {}


async def test_voice_note_limits(client, photo_store, monkeypatch):
    token = await citizen(client)
    report_id = await report_by(client, token)
    monkeypatch.setattr(settings, "MAX_VOICE_BYTES", 1024)
    assert (await speak(client, report_id, token, data=WEBM + b"\x00" * 2000)).status_code == 413
    monkeypatch.setattr(settings, "MAX_VOICE_BYTES", 3 * 1024 * 1024)
    assert (await speak(client, report_id, token)).status_code == 201
    assert (await speak(client, report_id, token)).status_code == 409  # one per report


async def test_voice_notes_are_off_when_storage_is_not_configured(client, monkeypatch):
    from app.core.storage import use_store

    token = await citizen(client)
    report_id = await report_by(client, token)
    use_store(None)
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", None)
    assert (await speak(client, report_id, token)).status_code == 503


# ---- the transcript comes back -------------------------------------------------------------


async def test_the_internal_endpoint_is_closed_without_the_right_key(client, photo_store, monkeypatch):
    await spoken_report(client)
    voice_id = (await note_row())["id"]
    assert (await transcript(client, voice_id, headers={})).status_code == 401
    assert (await transcript(client, voice_id, headers=API_KEY)).status_code == 401
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    assert (await transcript(client, voice_id)).status_code == 503
    assert (await note_row())["status"] == "pending"


async def test_a_transcript_replaces_the_placeholder_description_and_queues_triage(client, photo_store):
    _, report_id = await spoken_report(client)
    voice_id = (await note_row())["id"]
    assert (await transcript(client, voice_id)).status_code == 200

    row = await note_row()
    assert row["status"] == "done" and row["language"] == "English" and row["model"] == "fake-whisper"
    assert row["transcript"] == "There is a deep pothole near the school."

    public = (await client.get(f"/api/v1/reports/{report_id}")).json()
    assert public["description"] == "There is a deep pothole near the school."
    queued = await events("ReportTriageRequested")
    assert queued[-1]["report_id"] == report_id and queued[-1]["description"] == public["description"]


async def test_a_typed_description_is_never_overwritten(client, photo_store):
    _, report_id = await spoken_report(client, description="A deep pothole in front of the bus stop.")
    before = len(await events("ReportTriageRequested"))
    assert (await transcript(client, (await note_row())["id"])).status_code == 200
    public = (await client.get(f"/api/v1/reports/{report_id}")).json()
    assert public["description"] == "A deep pothole in front of the bus stop."
    assert len(await events("ReportTriageRequested")) == before  # nothing new to triage


async def test_a_redelivered_transcript_changes_nothing(client, photo_store):
    await spoken_report(client)
    voice_id = (await note_row())["id"]
    await transcript(client, voice_id)
    again = await transcript(client, voice_id, {"status": "done", "transcript": "Something else entirely.", "language": "Hindi"})
    assert again.json() == {"ok": True, "ignored": True}
    assert (await note_row())["transcript"] == "There is a deep pothole near the school."
    assert len(await events("ReportTriageRequested")) == 2  # filing, and the one transcript


async def test_silence_and_failures_are_recorded_and_leave_the_report_alone(client, photo_store):
    _, report_id = await spoken_report(client)
    voice_id = (await note_row())["id"]
    assert (await transcript(client, voice_id, {"status": "done", "transcript": "   "})).status_code == 200
    row = await note_row()
    assert row["status"] == "failed" and row["error"]
    public = (await client.get(f"/api/v1/reports/{report_id}")).json()
    assert public["description"] == VOICE_PLACEHOLDER

    assert (await transcript(client, voice_id, {"status": "failed", "error": "model unavailable"})).status_code == 200
    assert (await note_row())["error"] == "model unavailable"


async def test_an_unknown_voice_note_is_a_404(client, photo_store):
    assert (await transcript(client, "00000000-0000-0000-0000-000000000000")).status_code == 404


async def test_a_long_transcript_is_cut_to_the_description_limit(client, photo_store):
    await spoken_report(client)
    voice_id = (await note_row())["id"]
    await transcript(client, voice_id, {"status": "done", "transcript": "word " * 3000})
    assert len((await note_row())["transcript"]) <= 5000


# ---- who can see it ------------------------------------------------------------------------


async def test_staff_see_the_recording_and_transcript(client, photo_store):
    _, report_id = await spoken_report(client)
    await transcript(client, (await note_row())["id"])
    detail = (await client.get(f"/api/v1/admin/reports/{report_id}", headers=API_KEY)).json()
    (note,) = detail["voice_notes"]
    assert note["transcript"] == "There is a deep pothole near the school."
    assert note["language"] == "English" and note["duration_seconds"] == 12 and note["url"].startswith("memory://")


async def test_voice_notes_never_reach_citizens_or_the_public(client, photo_store):
    token, report_id = await spoken_report(client)
    await transcript(client, (await note_row())["id"])
    mine = json.dumps((await client.get("/api/v1/me/reports", headers=bearer(token))).json())
    public = (await client.get(f"/api/v1/reports/{report_id}")).text
    for body in (mine, public):
        assert "voice" not in body and "transcript" not in body and "memory://" not in body
