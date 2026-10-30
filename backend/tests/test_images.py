import io
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image
from sqlalchemy import text

from app.core.config import settings
from app.core.images import ImageRejected, process_image
from app.core.storage import use_store
from app.db.session import engine
from tests.conftest import sample_report

API_KEY = {"X-API-Key": os.environ["ADMIN_API_KEY"]}
PASSWORD = "correct horse battery"


def jpeg(size=(400, 300), color=(120, 40, 40), exif=False) -> bytes:
    img = Image.new("RGB", size, color)
    out = io.BytesIO()
    if exif:
        tags = img.getexif()
        tags[0x010F] = "SecretCameraMaker"  # Make
        tags[0x013B] = "Owner Name"  # Artist
        img.save(out, "JPEG", exif=tags)
    else:
        img.save(out, "JPEG")
    return out.getvalue()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def citizen(client, email="asha@example.org"):
    r = await client.post("/api/v1/auth/register", json={"name": "Asha Rao", "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def report_by(client, token, **overrides):
    r = await client.post("/api/v1/reports/", json=sample_report(**overrides), headers=bearer(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def upload(client, report_id, token, data=None, name="photo.jpg", ctype="image/jpeg"):
    return await client.post(
        f"/api/v1/reports/{report_id}/images",
        files={"file": (name, data if data is not None else jpeg(), ctype)},
        headers=bearer(token),
    )


async def events(kind):
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT payload FROM outbox_events WHERE event_type = :t ORDER BY id"), {"t": kind})).all()
    return [r.payload for r in rows]


# ---- image processing --------------------------------------------------------------------


async def test_processing_strips_metadata_and_bounds_size():
    original = jpeg(size=(4000, 3000), exif=True)
    assert b"SecretCameraMaker" in original

    out = await process_image(original)
    assert b"SecretCameraMaker" not in out.data and b"Owner Name" not in out.data
    assert max(out.width, out.height) <= 2048
    assert out.content_type == "image/jpeg"
    assert not Image.open(io.BytesIO(out.data)).getexif()


@pytest.mark.parametrize(
    "data",
    [
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"this is not an image at all",
        b"",
        b"GIF89a" + b"\x00" * 20,
    ],
)
async def test_processing_rejects_non_photos(data):
    with pytest.raises(ImageRejected):
        await process_image(data)


async def test_processing_rejects_animation_tiny_and_enormous_images():
    frames = [Image.new("RGB", (100, 100), c) for c in ((255, 0, 0), (0, 255, 0))]
    gif = io.BytesIO()
    frames[0].save(gif, "GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(ImageRejected):
        await process_image(gif.getvalue())

    with pytest.raises(ImageRejected):
        await process_image(jpeg(size=(20, 20)))

    huge = io.BytesIO()
    Image.new("L", (7000, 7000)).save(huge, "PNG")  # 49 million pixels, tiny file
    with pytest.raises(ImageRejected):
        await process_image(huge.getvalue())


# ---- uploading ---------------------------------------------------------------------------


async def test_owner_can_upload_and_the_stored_file_is_clean(client, photo_store):
    token = await citizen(client)
    report_id = await report_by(client, token)

    r = await upload(client, report_id, token, jpeg(size=(3000, 2000), exif=True))
    assert r.status_code == 201
    body = r.json()
    assert body["width"] <= 2048

    (data, content_type), = photo_store.objects.values()
    assert content_type == "image/jpeg" and b"SecretCameraMaker" not in data


async def test_upload_requires_sign_in_and_ownership(client):
    owner = await citizen(client, "owner@example.org")
    other = await citizen(client, "other@example.org")
    report_id = await report_by(client, owner)

    anonymous = await client.post(f"/api/v1/reports/{report_id}/images", files={"file": ("p.jpg", jpeg(), "image/jpeg")})
    assert anonymous.status_code == 401
    assert (await upload(client, report_id, other)).status_code == 404  # same answer as "no such report"
    assert (await upload(client, "00000000-0000-0000-0000-000000000000", owner)).status_code == 404


async def test_an_anonymous_report_cannot_receive_photos(client):
    anonymous_report = (await client.post("/api/v1/reports/", json=sample_report())).json()["id"]
    token = await citizen(client)
    assert (await upload(client, anonymous_report, token)).status_code == 404


async def test_upload_limits(client, monkeypatch):
    token = await citizen(client)
    report_id = await report_by(client, token)

    assert (await upload(client, report_id, token, b"not an image", "x.jpg")).status_code == 422
    assert (await upload(client, report_id, token, b"<svg></svg>", "x.svg", "image/svg+xml")).status_code == 422

    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1000)
    assert (await upload(client, report_id, token, jpeg(size=(900, 900)))).status_code == 413
    monkeypatch.undo()

    for _ in range(settings.MAX_IMAGES_PER_REPORT):
        assert (await upload(client, report_id, token)).status_code == 201
    assert (await upload(client, report_id, token)).status_code == 409


async def test_uploads_are_off_when_storage_is_not_configured(client, monkeypatch):
    token = await citizen(client)
    report_id = await report_by(client, token)
    use_store(None)
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", None)  # the environment may define a real store
    r = await upload(client, report_id, token)
    assert r.status_code == 503



async def test_noisy_photos_are_shrunk_until_they_fit_a_hosted_models_limit():
    import random

    random.seed(1)
    noise = Image.frombytes("RGB", (2400, 2400), random.randbytes(2400 * 2400 * 3))  # incompressible
    raw = io.BytesIO()
    noise.save(raw, "PNG")
    out = await process_image(raw.getvalue())
    assert len(out.data) <= 2_500_000




# ---- hand-off to the ai-service -----------------------------------------------------------

INTERNAL = {"X-Internal-Key": "internal-test-key"}
FINDINGS = {
    "summary": "A pothole in the road.", "issue_visible": True, "suggested_category": "Road",
    "category_matches_report": True, "severity": "medium", "hazards": [],
    "recommended_action": "Repair it.", "image_quality": "good", "flags": [], "confidence": 0.8,
}


@pytest.fixture(autouse=True)
def internal_key(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "internal-test-key")


async def uploaded_report(client, token=None):
    token = token or await citizen(client)
    report_id = await report_by(client, token, title="Deep pothole on the main road")
    assert (await upload(client, report_id, token)).status_code == 201
    return token, report_id


async def image_row():
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT * FROM report_images"))).mappings().one()


def result(severity="medium", flags=None, provider="fake", **extra):
    body = {"status": "done", "severity": severity, "analysis": FINDINGS | {"severity": severity, "flags": flags or []},
            "provider": provider, "model": "fake-1", "attempts": 1}
    return body | extra


async def send(client, image_id, body, headers=INTERNAL):
    return await client.post(f"/api/v1/internal/images/{image_id}/analysis", json=body, headers=headers)


async def test_an_upload_queues_work_for_the_ai_service(client, photo_store):
    _, report_id = await uploaded_report(client)
    (sent,) = await events("ReportImageUploaded")
    row = await image_row()
    assert sent["image_id"] == str(row["id"]) and sent["report_id"] == report_id
    assert sent["storage_key"] == row["storage_key"] and sent["title"] == "Deep pothole on the main road"
    assert row["status"] == "pending"


async def test_the_internal_endpoint_is_closed_without_the_right_key(client, photo_store, monkeypatch):
    await uploaded_report(client)
    image_id = (await image_row())["id"]
    assert (await send(client, image_id, result(), headers={})).status_code == 401
    assert (await send(client, image_id, result(), headers={"X-Internal-Key": "wrong"})).status_code == 401
    assert (await send(client, image_id, result(), headers=API_KEY)).status_code == 401  # the admin key is not this key
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    assert (await send(client, image_id, result())).status_code == 503
    assert (await image_row())["status"] == "pending"


async def test_findings_are_stored_and_the_admin_sees_them(client, photo_store):
    _, report_id = await uploaded_report(client)
    image_id = (await image_row())["id"]
    assert (await send(client, image_id, result("medium"))).status_code == 200
    row = await image_row()
    assert row["status"] == "done" and row["severity"] == "medium" and row["analysis_model"] == "fake-1"
    assert row["analysis"]["summary"] == "A pothole in the road." and row["analyzed_at"] is not None
    detail = (await client.get(f"/api/v1/admin/reports/{report_id}", headers=API_KEY)).json()
    assert detail["images"][0]["findings"]["severity"] == "medium"


async def test_findings_never_reach_citizens_or_the_public(client, photo_store):
    token, report_id = await uploaded_report(client)
    await send(client, (await image_row())["id"], result("high"))
    mine = (await client.get("/api/v1/me/reports", headers=bearer(token))).json()
    assert "images" not in mine[0] and "analysis" not in json.dumps(mine)
    public = (await client.get(f"/api/v1/reports/{report_id}")).text
    assert "analysis" not in public and "findings" not in public


async def test_serious_findings_message_the_admin_but_minor_ones_do_not(client, photo_store):
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO officers (id, name, role, telegram_chat_id, active) VALUES (gen_random_uuid(), 'Admin', 'admin', '999', true)"))
    await uploaded_report(client)
    image_id = (await image_row())["id"]
    await send(client, image_id, result("low"))
    assert await events("ReportImageAnalyzed") == []

    await uploaded_report(client, await citizen(client, "second@example.org"))
    async with engine.connect() as conn:
        second = (await conn.execute(text("SELECT id FROM report_images WHERE status = 'pending'"))).scalar_one()
    await send(client, second, result("critical"))
    (sent,) = await events("ReportImageAnalyzed")
    assert sent["severity"] == "critical" and sent["recipient"]["chat_id"] == "999"


async def test_demo_output_never_pages_anyone(client, photo_store):
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO officers (id, name, role, telegram_chat_id, active) VALUES (gen_random_uuid(), 'Admin', 'admin', '999', true)"))
    await uploaded_report(client)
    await send(client, (await image_row())["id"], result("critical", provider="mock"))
    (sent,) = await events("ReportImageAnalyzed")
    assert "recipient" not in sent


async def test_inappropriate_content_alerts_the_admin_even_at_low_severity(client, photo_store):
    await uploaded_report(client)
    await send(client, (await image_row())["id"], result("low", flags=["inappropriate"]))
    assert len(await events("ReportImageAnalyzed")) == 1


async def test_a_redelivered_result_changes_nothing_and_alerts_nobody_twice(client, photo_store):
    await uploaded_report(client)
    image_id = (await image_row())["id"]
    await send(client, image_id, result("critical"))
    again = await send(client, image_id, result("low"))
    assert again.status_code == 200 and again.json()["ignored"] is True
    assert (await image_row())["severity"] == "critical"
    assert len(await events("ReportImageAnalyzed")) == 1


async def test_a_failed_analysis_is_recorded(client, photo_store):
    await uploaded_report(client)
    image_id = (await image_row())["id"]
    r = await send(client, image_id, {"status": "failed", "error": "wrong model name", "attempts": 3})
    assert r.status_code == 200
    row = await image_row()
    assert row["status"] == "failed" and row["error"] == "wrong model name" and row["attempts"] == 3


async def test_bad_results_are_refused(client, photo_store):
    await uploaded_report(client)
    image_id = (await image_row())["id"]
    assert (await send(client, image_id, {"status": "done"})).status_code == 422
    assert (await send(client, image_id, result(severity="apocalyptic"))).status_code == 422
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (await send(client, unknown, result())).status_code == 404
    assert (await image_row())["status"] == "pending"
