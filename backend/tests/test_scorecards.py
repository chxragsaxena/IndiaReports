"""Public scorecards: how each area is doing at fixing what is reported in it."""

import pytest
from sqlalchemy import text

from app.core.cache import clear_local_cache
from app.db.session import engine
from tests.test_auth import bearer, register
from tests.test_staff import citizen_report, email_on, two_cities  # noqa: F401  (email_on is an autouse fixture)


@pytest.fixture(autouse=True)
def fresh_cache():
    clear_local_cache()


async def card(client, name="Andheri ward"):
    clear_local_cache()
    body = (await client.get("/api/v1/scorecards")).json()
    return next((a for a in body["areas"] if a["area"] == name), None)


async def sql(query, **params):
    async with engine.begin() as conn:
        await conn.execute(text(query), params)


async def test_an_area_is_marked_on_what_it_resolved_in_time_and_what_slipped(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    reports = [await citizen_report(client, citizen) for _ in range(6)]

    for r in reports[:3]:  # resolved straight away
        assert (await client.patch(f"/api/v1/reports/{r['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))).status_code == 200
    await sql("UPDATE reports SET assigned_at = now() - interval '10 days' WHERE id = :id", id=reports[3]["id"])  # overdue
    await sql("UPDATE reports SET escalated_at = now() WHERE id = :id", id=reports[4]["id"])  # escalated to the admin
    await sql("""UPDATE reports SET triage = '{"is_spam": true}' WHERE id = :id""", id=reports[5]["id"])  # not counted

    a = await card(client)
    assert a["officers"] == ["Asha (Mumbai)"]
    assert a["received"] == 5 and a["resolved"] == 3 and a["late_open"] == 2 and a["escalated"] == 1
    assert a["in_time_rate"] == 0.6 and a["ranked"] is True  # 3 of the 5 whose deadline is decided
    assert a["median_resolution_hours"] is not None and a["median_resolution_hours"] < 1


async def test_reports_still_inside_their_deadline_are_not_held_against_the_area(client):
    await two_cities(client)
    citizen = (await register(client))["access_token"]
    for _ in range(3):
        await citizen_report(client, citizen)
    a = await card(client)
    assert a["received"] == 3 and a["open_now"] == 3 and a["late_open"] == 0
    assert a["in_time_rate"] is None and a["ranked"] is False  # nothing judged yet, so no score


async def test_a_disputed_fix_counts_towards_the_reopen_rate(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    report = await citizen_report(client, citizen)
    await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))
    assert (await client.post(f"/api/v1/reports/{report['id']}/reopen", json={"reason": "still broken"}, headers=bearer(citizen))).status_code == 200

    a = await card(client)
    assert a["reopened"] == 1 and a["reopen_rate"] == 1.0 and a["resolved"] == 0


async def test_each_area_has_its_own_card_and_the_page_is_public(client):
    asha, ravi = await two_cities(client)
    citizen = (await register(client))["access_token"]
    await citizen_report(client, citizen)
    await citizen_report(client, citizen, latitude=28.6, longitude=77.2, city="Delhi")

    clear_local_cache()
    response = await client.get("/api/v1/scorecards")  # no sign-in
    assert response.status_code == 200
    names = sorted(a["area"] for a in response.json()["areas"])
    assert names == ["Andheri ward", "Delhi ward"]
    assert "title" not in response.text and "description" not in response.text  # counts only, never report text
    assert response.json()["resolve_within_days"] == 7.0


async def test_reports_outside_every_area_are_not_on_any_card(client):
    await two_cities(client)
    citizen = (await register(client))["access_token"]
    await citizen_report(client, citizen, latitude=13.08, longitude=80.27, city="Chennai")  # no area covers it
    clear_local_cache()
    assert (await client.get("/api/v1/scorecards")).json()["areas"] == []
