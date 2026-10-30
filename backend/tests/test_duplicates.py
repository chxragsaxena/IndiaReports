"""Finding the same problem reported twice, and letting people say "me too"."""

import os

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.services.similarity import text_match, words
from tests.conftest import sample_report

API_KEY = {"X-API-Key": os.environ["ADMIN_API_KEY"]}
PASSWORD = "correct horse battery"
LAT, LNG = 28.6139, 77.2090
METRE = 1 / 111_000  # degrees of latitude per metre, near enough for tests


@pytest.fixture(autouse=True)
def email_on(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def citizen(client, email):
    r = await client.post("/api/v1/auth/register", json={"name": email.split("@")[0].title(), "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def file_report(client, token=None, metres_north=0.0, **overrides):
    body = sample_report(latitude=LAT + metres_north * METRE, longitude=LNG, **overrides)
    r = await client.post("/api/v1/reports/", json=body, headers=bearer(token) if token else {})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def similar(client, metres_north=0.0, category="Road", title="Large pothole", description="near the market"):
    r = await client.get("/api/v1/reports/similar", params={
        "latitude": LAT + metres_north * METRE, "longitude": LNG, "category": category, "title": title, "description": description,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_words_work_in_any_script_and_ignore_tiny_words():
    assert words("A big pothole!") == {"big", "pothole"}
    assert "गड्ढा" in words("सड़क पर गड्ढा")
    assert text_match({"pothole", "road"}, {"pothole", "road", "market", "deep"}) == 1.0
    assert text_match(set(), {"x"}) == 0.0


async def test_a_report_right_here_with_the_same_wording_is_found(client):
    report_id = await file_report(client, title="Large pothole near the market")
    found = await similar(client, metres_north=20, title="Pothole near market gate")
    assert [f["id"] for f in found] == [report_id]
    assert found[0]["distance_m"] <= 25 and found[0]["affected_count"] == 1
    assert found[0]["latitude"] and found[0]["longitude"]  # lets the person open it on the map to check


async def test_only_close_open_reports_of_the_same_kind_are_found(client):
    await file_report(client, title="Large pothole near the market")
    assert await similar(client, metres_north=400) == []  # too far
    assert await similar(client, category="Garbage") == []  # a different kind of problem


async def test_in_between_distances_need_similar_wording(client):
    await file_report(client, title="Large pothole near the market", description="Deep hole in the left lane")
    same_words = await similar(client, metres_north=100, title="Pothole near the market", description="deep hole")
    other_words = await similar(client, metres_north=100, title="Cracked pavement", description="loose tiles outside shop")
    assert len(same_words) == 1 and other_words == []
    # Practically the same spot counts whatever the wording (or the language).
    assert len(await similar(client, metres_north=10, title="सड़क में गड्ढा", description="बहुत गहरा")) == 1


async def test_resolved_reports_are_not_offered(client):
    report_id = await file_report(client, title="Large pothole near the market")
    r = await client.patch(f"/api/v1/reports/{report_id}/status", json={"status": "RESOLVED"}, headers=API_KEY)
    assert r.status_code == 200
    assert await similar(client, title="Large pothole near the market") == []


async def test_a_copy_is_flagged_for_staff_but_nothing_is_hidden(client):
    first = await file_report(client, title="Large pothole near the market")
    second = await file_report(client, metres_north=15, title="Big pothole near market")
    detail = (await client.get(f"/api/v1/admin/reports/{second}", headers=API_KEY)).json()
    assert detail["possible_duplicate"]["id"] == first
    assert (await client.get(f"/api/v1/admin/reports/{first}", headers=API_KEY)).json()["possible_duplicate"] is None
    assert (await client.get(f"/api/v1/reports/{second}")).status_code == 200
    # A third report links to the original, not to the copy.
    third = await file_report(client, metres_north=10, title="Pothole near market")
    assert (await client.get(f"/api/v1/admin/reports/{third}", headers=API_KEY)).json()["possible_duplicate"]["id"] == first


async def test_me_too_counts_each_person_once_and_not_the_reporter(client):
    owner = await citizen(client, "owner@example.org")
    fan = await citizen(client, "fan@example.org")
    report_id = await file_report(client, owner, title="Large pothole near the market")
    url = f"/api/v1/reports/{report_id}/support"

    own = await client.post(url, headers=bearer(owner))
    assert own.json() == {"affected_count": 1, "added": False}
    first = await client.post(url, headers=bearer(fan))
    assert first.json() == {"affected_count": 2, "added": True}
    again = await client.post(url, headers=bearer(fan))
    assert again.json() == {"affected_count": 2, "added": False}

    assert (await client.get(f"/api/v1/reports/{report_id}")).json()["affected_count"] == 2
    assert (await client.get("/api/v1/admin/reports", headers=API_KEY)).json()["items"][0]["affected_count"] == 2
    assert (await similar(client, title="Large pothole near the market"))[0]["affected_count"] == 2


async def test_me_too_needs_sign_in_and_an_open_report(client):
    owner = await citizen(client, "owner@example.org")
    fan = await citizen(client, "fan@example.org")
    report_id = await file_report(client, owner)
    url = f"/api/v1/reports/{report_id}/support"
    assert (await client.post(url)).status_code == 401
    assert (await client.post("/api/v1/reports/00000000-0000-0000-0000-000000000000/support", headers=bearer(fan))).status_code == 404
    await client.patch(f"/api/v1/reports/{report_id}/status", json={"status": "RESOLVED"}, headers=API_KEY)
    assert (await client.post(url, headers=bearer(fan))).status_code == 409


async def test_people_who_said_me_too_are_emailed_when_it_is_fixed(client):
    owner = await citizen(client, "owner@example.org")
    fan = await citizen(client, "fan@example.org")
    report_id = await file_report(client, owner)
    await client.post(f"/api/v1/reports/{report_id}/support", headers=bearer(fan))
    r = await client.patch(
        f"/api/v1/reports/{report_id}/status", json={"status": "RESOLVED", "note": "Patched."}, headers=API_KEY
    )
    assert r.status_code == 200
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT to_email FROM email_jobs WHERE dedupe_key LIKE 'resolved:%'"))).all()
    assert sorted(r.to_email for r in rows) == ["fan@example.org", "owner@example.org"]
