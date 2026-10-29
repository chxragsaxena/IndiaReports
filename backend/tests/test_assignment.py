import os

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.events.escalation import escalate_once
from tests.conftest import sample_report

ADMIN = {"X-API-Key": os.environ["ADMIN_API_KEY"]}

MUMBAI = {"latitude": 19.076, "longitude": 72.877, "city": "Mumbai", "state": "Maharashtra"}


def square(min_lng, min_lat, max_lng, max_lat):
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lng, min_lat], [max_lng, min_lat], [max_lng, max_lat],
            [min_lng, max_lat], [min_lng, min_lat],
        ]],
    }


async def make_area(client, name, geometry):
    r = await client.post("/api/v1/admin/areas", json={"name": name, "geometry": geometry}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def make_officer(client, name, chat_id, area_id=None, role="officer"):
    r = await client.post(
        "/api/v1/admin/officers",
        json={"name": name, "role": role, "telegram_chat_id": chat_id, "area_id": area_id},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def events(event_type=None):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT event_type, payload FROM outbox_events ORDER BY id"))
        ).all()
    return [(r.event_type, r.payload) for r in rows if event_type in (None, r.event_type)]


async def file_report(client, **overrides):
    r = await client.post("/api/v1/reports/", json=sample_report(**(MUMBAI | overrides)))
    assert r.status_code == 201, r.text
    return r.json()


async def test_report_is_routed_to_the_officer_of_the_containing_area(client):
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha (Andheri)", "111", ward)
    await make_officer(client, "Main Admin", "999", role="admin")

    report = await file_report(client)

    created = (await events("ReportCreated"))[0][1]
    assert created["recipient"]["name"] == "Asha (Andheri)"
    assert created["recipient"]["chat_id"] == "111"
    assert created["recipient"]["ack_token"]
    assert report["assigned_at"] is not None
    assert report["acknowledged_at"] is None


async def test_smallest_containing_area_wins(client):
    district = await make_area(client, "Maharashtra", square(72.0, 15.0, 80.0, 22.0))
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "District officer", "222", district)
    await make_officer(client, "Ward officer", "111", ward)

    await file_report(client)

    assert (await events("ReportCreated"))[0][1]["recipient"]["name"] == "Ward officer"


async def test_report_outside_every_area_goes_to_admin(client):
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha", "111", ward)
    await make_officer(client, "Main Admin", "999", role="admin")

    await file_report(client, latitude=28.61, longitude=77.21, city="Delhi", state="Delhi")

    created = (await events("ReportCreated"))[0][1]
    assert created["recipient"]["role"] == "admin"


async def test_no_officers_means_no_recipient_and_no_failure(client):
    report = await file_report(client)
    assert report["assigned_at"] is None
    assert "recipient" not in (await events("ReportCreated"))[0][1]


async def test_invalid_polygon_is_rejected(client):
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}
    r = await client.post("/api/v1/admin/areas", json={"name": "Bowtie", "geometry": bowtie}, headers=ADMIN)
    assert r.status_code == 422

    r = await client.post(
        "/api/v1/admin/areas", json={"name": "Point", "geometry": {"type": "Point", "coordinates": [1, 1]}},
        headers=ADMIN,
    )
    assert r.status_code == 422


async def test_admin_endpoints_require_the_api_key(client):
    assert (await client.get("/api/v1/admin/areas")).status_code == 401
    r = await client.post("/api/v1/admin/officers", json={"name": "X Y", "telegram_chat_id": "1"})
    assert r.status_code == 401


async def test_officer_rules(client):
    area = await make_area(client, "Area A", square(72.8, 19.0, 72.95, 19.15))
    # An officer needs an area; the admin must not have one; only one active admin.
    r = await client.post("/api/v1/admin/officers",
                          json={"name": "No Area", "telegram_chat_id": "1"}, headers=ADMIN)
    assert r.status_code == 422
    r = await client.post("/api/v1/admin/officers",
                          json={"name": "Bad Admin", "role": "admin", "telegram_chat_id": "1", "area_id": area},
                          headers=ADMIN)
    assert r.status_code == 422
    r = await client.post("/api/v1/admin/officers",
                          json={"name": "Bad Chat", "telegram_chat_id": "not valid!", "area_id": area},
                          headers=ADMIN)
    assert r.status_code == 422
    await make_officer(client, "Admin One", "9", role="admin")
    r = await client.post("/api/v1/admin/officers",
                          json={"name": "Admin Two", "role": "admin", "telegram_chat_id": "8"}, headers=ADMIN)
    assert r.status_code == 409


async def test_acknowledge_with_signed_token(client):
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha", "111", ward)
    report = await file_report(client)
    token = (await events("ReportCreated"))[0][1]["recipient"]["ack_token"]
    url = f"/api/v1/reports/{report['id']}/acknowledge"

    assert (await client.post(url, json={"token": "x" * 40})).status_code == 403

    ok = await client.post(url, json={"token": token})
    assert ok.status_code == 200
    assert ok.json()["acknowledged_at"] is not None
    assert ok.json()["status"] == "IN_PROGRESS"

    # Idempotent: a second click changes nothing and emits no second status event.
    assert (await client.post(url, json={"token": token})).status_code == 200
    assert len(await events("ReportStatusChanged")) == 1


async def test_unacknowledged_report_escalates_to_admin_once(client, monkeypatch):
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha", "111", ward)
    await make_officer(client, "Main Admin", "999", role="admin")
    report = await file_report(client)
    officer_token = (await events("ReportCreated"))[0][1]["recipient"]["ack_token"]

    # Not overdue yet: nothing happens.
    assert await escalate_once() == 0

    monkeypatch.setattr(settings, "ESCALATION_AFTER_SECONDS", 0)
    assert await escalate_once() == 1
    assert await escalate_once() == 0  # at most once per report

    escalated = (await events("ReportEscalated"))
    assert len(escalated) == 1
    payload = escalated[0][1]
    assert payload["recipient"]["role"] == "admin"
    assert payload["recipient"]["chat_id"] == "999"
    assert payload["previous_assignee"] == "Asha"
    assert payload["report_id"] == report["id"]

    # The officer's old link no longer works; the admin's does.
    url = f"/api/v1/reports/{report['id']}/acknowledge"
    assert (await client.post(url, json={"token": officer_token})).status_code == 403
    assert (await client.post(url, json={"token": payload["recipient"]["ack_token"]})).status_code == 200


async def test_only_resolved_or_admin_assigned_reports_are_spared_escalation(client, monkeypatch):
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha", "111", ward)
    await make_officer(client, "Main Admin", "999", role="admin")

    # Resolved in time: nothing to escalate.
    done = await file_report(client)
    await client.patch(f"/api/v1/reports/{done['id']}/status", json={"status": "RESOLVED"}, headers=ADMIN)

    # Fell outside every area, so it went straight to the admin: nothing to escalate to.
    await file_report(client, latitude=28.61, longitude=77.21, city="Delhi", state="Delhi")

    monkeypatch.setattr(settings, "ESCALATION_AFTER_SECONDS", 0)
    assert await escalate_once() == 0
    assert await events("ReportEscalated") == []


async def test_acknowledging_or_starting_work_does_not_stop_the_clock(client, monkeypatch):
    """The officer has to RESOLVE it in time; saying "seen" or "in progress" is not enough."""
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha", "111", ward)
    await make_officer(client, "Main Admin", "999", role="admin")

    seen = await file_report(client)
    token = (await events("ReportCreated"))[0][1]["recipient"]["ack_token"]
    await client.post(f"/api/v1/reports/{seen['id']}/acknowledge", json={"token": token})

    working = await file_report(client)
    await client.patch(f"/api/v1/reports/{working['id']}/status", json={"status": "IN_PROGRESS"}, headers=ADMIN)

    monkeypatch.setattr(settings, "ESCALATION_AFTER_SECONDS", 0)
    assert await escalate_once() == 2
    escalated = {p["report_id"] for _, p in await events("ReportEscalated")}
    assert escalated == {seen["id"], working["id"]}


async def test_no_admin_means_no_escalation(client, monkeypatch):
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha", "111", ward)
    await file_report(client)

    monkeypatch.setattr(settings, "ESCALATION_AFTER_SECONDS", 0)
    assert await escalate_once() == 0


async def test_admin_report_list_shows_assignee_and_filters(client):
    ward = await make_area(client, "Andheri ward", square(72.8, 19.0, 72.95, 19.15))
    await make_officer(client, "Asha Rao", "111", ward)
    first = await file_report(client, title="Pothole one")
    await file_report(client, title="Pothole two")
    await client.patch(f"/api/v1/reports/{first['id']}/status", json={"status": "IN_PROGRESS"}, headers=ADMIN)

    assert (await client.get("/api/v1/admin/reports")).status_code == 401  # key required

    everything = (await client.get("/api/v1/admin/reports", headers=ADMIN)).json()
    assert [r["title"] for r in everything["items"]] == ["Pothole two", "Pothole one"]  # newest first
    assert everything["items"][0]["assignee_name"] == "Asha Rao"
    assert everything["next_before"] is None

    needs = (await client.get("/api/v1/admin/reports", params={"needs_attention": True}, headers=ADMIN)).json()
    assert [r["title"] for r in needs["items"]] == ["Pothole two"]  # the other was acted on


async def test_admin_report_list_pages_by_keyset(client):
    for i in range(3):
        await file_report(client, title=f"Report {i}")
    page1 = (await client.get("/api/v1/admin/reports", params={"limit": 2}, headers=ADMIN)).json()
    assert len(page1["items"]) == 2 and page1["next_before"]
    page2 = (
        await client.get("/api/v1/admin/reports", params={"limit": 2, "before": page1["next_before"]}, headers=ADMIN)
    ).json()
    assert [r["title"] for r in page2["items"]] == ["Report 0"]
    assert page2["next_before"] is None
