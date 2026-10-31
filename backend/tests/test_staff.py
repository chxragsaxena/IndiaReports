"""Area officers (decentralised administration), resolving, and the citizen's window to check."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.events.lifecycle import archive_once
from app.events.rollup import rollup_once
from tests.conftest import sample_report, verify_all_emails
from tests.test_assignment import ADMIN, MUMBAI, events, make_area, square
from tests.test_auth import PASSWORD, bearer, register

ANDHERI = square(72.8, 19.0, 72.95, 19.15)
DELHI = square(77.0, 28.4, 77.4, 28.8)


@pytest.fixture(autouse=True)
def email_on(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example")


async def add_officer(client, name, email, area_id, role="officer"):
    r = await client.post(
        "/api/v1/admin/officers",
        json={"name": name, "role": role, "area_id": area_id, "email": email, "password": PASSWORD},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def citizen_report(client, token, **overrides):
    r = await client.post("/api/v1/reports/", json=sample_report(**(MUMBAI | overrides)), headers=bearer(token))
    assert r.status_code == 201, r.text
    return r.json()


async def queued_emails():
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT to_email, subject, body, sent_at FROM email_jobs ORDER BY id"))).all()
    return rows


async def two_cities(client):
    mumbai, delhi = await make_area(client, "Andheri ward", ANDHERI), await make_area(client, "Delhi ward", DELHI)
    asha = await add_officer(client, "Asha (Mumbai)", "asha@city.example", mumbai)
    ravi = await add_officer(client, "Ravi (Delhi)", "ravi@city.example", delhi)
    await add_officer(client, "Main Admin", "main@city.example", None, role="admin")
    return asha, ravi


# ---- who sees what -------------------------------------------------------------------


async def test_an_officer_sees_only_the_reports_of_their_own_area(client):
    asha, ravi = await two_cities(client)
    citizen = (await register(client))["access_token"]
    mine = await citizen_report(client, citizen)
    theirs = await citizen_report(client, citizen, latitude=28.6, longitude=77.2, city="Delhi")

    asha_list = (await client.get("/api/v1/admin/reports", headers=bearer(asha))).json()["items"]
    assert [r["id"] for r in asha_list] == [mine["id"]]
    ravi_list = (await client.get("/api/v1/admin/reports", headers=bearer(ravi))).json()["items"]
    assert [r["id"] for r in ravi_list] == [theirs["id"]]

    # Another area's report looks exactly like one that does not exist: no probing.
    assert (await client.get(f"/api/v1/admin/reports/{theirs['id']}", headers=bearer(asha))).status_code == 404
    assert (await client.get(f"/api/v1/admin/reports/{mine['id']}", headers=bearer(asha))).status_code == 200
    patch = await client.patch(f"/api/v1/reports/{theirs['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))
    assert patch.status_code == 404
    still = (await client.get(f"/api/v1/reports/{theirs['id']}")).json()
    assert still["status"] == "OPEN"


async def test_the_main_admin_sees_everything_and_only_they_manage_the_team(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    await citizen_report(client, citizen)
    await citizen_report(client, citizen, latitude=28.6, longitude=77.2, city="Delhi")

    main = (await client.post("/api/v1/auth/login", json={"email": "main@city.example", "password": PASSWORD})).json()["access_token"]
    assert len((await client.get("/api/v1/admin/reports", headers=bearer(main))).json()["items"]) == 2

    for path in ("/api/v1/admin/officers", "/api/v1/admin/areas"):
        assert (await client.get(path, headers=bearer(asha))).status_code == 403
        assert (await client.get(path, headers=bearer(main))).status_code == 200
    made = await client.post(
        "/api/v1/admin/users", json={"name": "X Person", "email": "x@x.example", "password": PASSWORD}, headers=bearer(asha)
    )
    assert made.status_code == 403
    area = await client.post("/api/v1/admin/areas", json={"name": "Hack", "geometry": ANDHERI}, headers=bearer(asha))
    assert area.status_code == 403


async def test_citizens_and_unlinked_officers_are_kept_out(client):
    citizen = await register(client)
    assert (await client.get("/api/v1/admin/reports", headers=bearer(citizen["access_token"]))).status_code == 403

    # An account marked officer but not tied to an area has no queue to show.
    await client.post(
        "/api/v1/admin/users", json={"name": "Loose Officer", "email": "loose@x.example", "password": PASSWORD, "role": "citizen"},
        headers=ADMIN,
    )
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET role = 'officer' WHERE email = 'loose@x.example'"))
    login = await client.post("/api/v1/auth/login", json={"email": "loose@x.example", "password": PASSWORD})
    r = await client.get("/api/v1/admin/reports", headers=bearer(login.json()["access_token"]))
    assert r.status_code == 403 and "not linked" in r.json()["detail"]


async def test_creating_an_officer_links_or_creates_the_account(client):
    area = await make_area(client, "Andheri ward", ANDHERI)
    existing = await register(client, email="neighbour@x.example")

    # An existing citizen is linked and becomes an officer; no password needed.
    r = await client.post(
        "/api/v1/admin/officers", json={"name": "Neha", "role": "officer", "area_id": area, "email": "neighbour@x.example"},
        headers=ADMIN,
    )
    assert r.status_code == 201 and r.json()["email"] == "neighbour@x.example" and r.json()["area_name"] == "Andheri ward"
    me = await client.get("/api/v1/auth/me", headers=bearer(existing["access_token"]))
    assert me.json()["role"] == "officer"

    # A new email needs a password.
    r = await client.post(
        "/api/v1/admin/officers", json={"name": "Omar", "role": "officer", "area_id": area, "email": "new@x.example"},
        headers=ADMIN,
    )
    assert r.status_code == 422

    # The same account cannot be two officers.
    r = await client.post(
        "/api/v1/admin/officers", json={"name": "Neha Two", "role": "officer", "area_id": area, "email": "neighbour@x.example"},
        headers=ADMIN,
    )
    assert r.status_code == 409


async def test_staff_profile_describes_the_scope(client):
    asha, _ = await two_cities(client)
    me = (await client.get("/api/v1/admin/me", headers=bearer(asha))).json()
    assert me["is_main"] is False and me["area_name"] == "Andheri ward" and me["name"] == "Asha (Mumbai)"
    assert me["resolve_within_seconds"] == settings.ESCALATION_AFTER_SECONDS
    assert (await client.get("/api/v1/admin/me", headers=ADMIN)).json()["is_main"] is True


# ---- resolving, and telling the citizen ----------------------------------------------


async def test_resolving_records_who_and_why_and_emails_the_citizen(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client, email="citizen@x.example", name="Chirag"))["access_token"]
    report = await citizen_report(client, citizen)
    await verify_all_emails()  # report emails only go to confirmed addresses

    r = await client.patch(
        f"/api/v1/reports/{report['id']}/status",
        json={"status": "RESOLVED", "note": "Filled with asphalt on Tuesday."},
        headers=bearer(asha),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "RESOLVED" and body["resolved_at"] and body["resolution_note"] == "Filled with asphalt on Tuesday."

    async with engine.connect() as conn:
        by = (await conn.execute(text("SELECT u.email FROM reports r JOIN users u ON u.id = r.resolved_by"))).scalar_one()
    assert by == "asha@city.example"

    mails = [m for m in await queued_emails() if m.to_email == "citizen@x.example" and m.subject.startswith("Resolved")]
    assert len(mails) == 1
    assert mails[0].subject == "Resolved: Large pothole"
    assert "Filled with asphalt on Tuesday." in mails[0].body
    assert "reopen" in mails[0].body and "3 days" in mails[0].body
    assert "https://app.example/my-reports" in mails[0].body

    # Saying it again changes nothing and sends nothing more.
    again = await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))
    assert again.status_code == 200
    assert len([m for m in await queued_emails() if m.to_email == "citizen@x.example" and m.subject.startswith("Resolved")]) == 1


async def test_an_anonymous_report_resolves_without_an_email(client):
    asha, _ = await two_cities(client)
    anon = await client.post("/api/v1/reports/", json=sample_report(**MUMBAI))
    assert anon.status_code == 201
    r = await client.patch(f"/api/v1/reports/{anon.json()['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))
    assert r.status_code == 200
    assert not [m for m in await queued_emails() if m.subject.startswith("Resolved")]


async def test_no_email_is_queued_when_email_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "off")
    asha, _ = await two_cities(client)
    citizen = (await register(client, email="citizen@x.example"))["access_token"]
    report = await citizen_report(client, citizen)
    await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))
    assert await queued_emails() == []


async def test_the_officer_is_emailed_when_a_report_lands_in_their_area(client):
    await two_cities(client)
    citizen = (await register(client, email="citizen@x.example"))["access_token"]
    await citizen_report(client, citizen)
    mails = [m for m in await queued_emails() if not m.subject.startswith("Confirm")]  # the sign-up confirmation is not this email
    assert [m.to_email for m in mails] == ["asha@city.example"]
    assert "New report in your area" in mails[0].subject and "7 days" in mails[0].body


# ---- the citizen's window: confirm, reopen, then it leaves the map -------------------


async def pins(client):
    r = await client.get("/api/v1/reports/pins", params={"min_lat": 18, "max_lat": 20, "min_lng": 72, "max_lng": 74})
    return r.json()["pins"]


async def resolved_report(client, asha, citizen):
    report = await citizen_report(client, citizen)
    r = await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))
    assert r.status_code == 200
    return report


async def test_resolved_reports_stay_on_the_map_during_the_window_then_leave(client, monkeypatch):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    report = await resolved_report(client, asha, citizen)
    await rollup_once()

    # Inside the window: still visible, nothing archived.
    assert await archive_once() == 0
    assert [p["id"] for p in await pins(client)] == [report["id"]]

    monkeypatch.setattr(settings, "RESOLVED_VISIBLE_SECONDS", 0)
    assert await archive_once() == 1
    assert await archive_once() == 0  # once only
    await rollup_once()

    from app.core.cache import clear_local_cache
    from app.core.redis import get_redis

    clear_local_cache()
    if get_redis() is not None:
        await get_redis().flushdb()  # the shared cache would otherwise keep serving the pins from before (throwaway test Redis only)
    assert await pins(client) == []
    listed = (await client.get("/api/v1/reports/", params={"min_lat": 18, "max_lat": 20, "min_lng": 72, "max_lng": 74})).json()
    assert listed == []
    clusters = (
        await client.get("/api/v1/reports/clusters", params={"min_lat": 6, "max_lat": 37, "min_lng": 68, "max_lng": 98, "zoom": 4})
    ).json()
    assert sum(c["count"] for c in clusters) == 0
    dash = (await client.get("/api/v1/reports/dashboard")).json()
    assert dash["total_reports"] == 0 and dash["resolved_reports"] == 0 and dash["recent_reports"] == []

    # It is kept: the reporter still has it, and so does the officer who resolved it.
    mine = (await client.get("/api/v1/me/reports", headers=bearer(citizen))).json()
    assert [r["id"] for r in mine] == [report["id"]] and mine[0]["archived_at"]
    assert len((await client.get("/api/v1/admin/reports", params={"status": "RESOLVED"}, headers=bearer(asha))).json()["items"]) == 1


async def test_rebuilding_the_rollup_leaves_archived_reports_out(client, monkeypatch):
    from app.db.session import AsyncSessionLocal
    from app.services import cell_service

    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    await resolved_report(client, asha, citizen)
    await citizen_report(client, citizen)
    monkeypatch.setattr(settings, "RESOLVED_VISIBLE_SECONDS", 0)
    await archive_once()

    async with AsyncSessionLocal() as db:
        await cell_service.rebuild(db)
        await db.commit()
        total = (await db.execute(text("SELECT sum(cnt) FROM report_cells WHERE level = 3"))).scalar_one()
    assert total == 1  # only the report that is still open


async def test_the_citizen_can_confirm_the_fix_and_it_leaves_the_map(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    report = await resolved_report(client, asha, citizen)

    r = await client.post(f"/api/v1/reports/{report['id']}/confirm", headers=bearer(citizen))
    assert r.status_code == 200 and r.json()["confirmed_at"]
    assert await archive_once() == 1  # no waiting for the window once the reporter has confirmed


async def test_the_citizen_can_reopen_and_the_officer_is_told(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    report = await resolved_report(client, asha, citizen)
    before = (await client.get(f"/api/v1/reports/{report['id']}")).json()

    r = await client.post(
        f"/api/v1/reports/{report['id']}/reopen", json={"reason": "The hole is still there."}, headers=bearer(citizen)
    )
    assert r.status_code == 200
    reopened = r.json()
    assert reopened["status"] == "OPEN" and reopened["resolved_at"] is None and reopened["resolution_note"] is None
    assert reopened["acknowledged_at"] is None
    assert reopened["assigned_at"] >= before["assigned_at"]  # a fresh deadline

    changed = [p for t, p in await events("ReportStatusChanged") if p["old_status"] == "RESOLVED"]
    assert changed and changed[0]["new_status"] == "OPEN"
    mail = [m for m in await queued_emails() if m.subject.startswith("Reopened")]
    assert len(mail) == 1 and mail[0].to_email == "asha@city.example" and "The hole is still there." in mail[0].body

    # And it is back in the officer's queue as open work.
    open_items = (await client.get("/api/v1/admin/reports", params={"status": "OPEN"}, headers=bearer(asha))).json()["items"]
    assert [i["id"] for i in open_items] == [report["id"]]


async def test_only_the_reporter_can_check_and_only_while_it_is_on_the_map(client, monkeypatch):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    stranger = (await register(client, email="stranger@x.example"))["access_token"]
    report = await resolved_report(client, asha, citizen)

    for action in ("confirm", "reopen"):
        url = f"/api/v1/reports/{report['id']}/{action}"
        assert (await client.post(url, json={}, headers=bearer(stranger))).status_code == 404  # not yours
        assert (await client.post(url, json={})).status_code == 401  # not signed in

    # A report that is not resolved cannot be confirmed or reopened.
    open_report = await citizen_report(client, citizen)
    assert (await client.post(f"/api/v1/reports/{open_report['id']}/reopen", json={}, headers=bearer(citizen))).status_code == 409

    # After it has left the map the window is over.
    monkeypatch.setattr(settings, "RESOLVED_VISIBLE_SECONDS", 0)
    await archive_once()
    for action in ("confirm", "reopen"):
        r = await client.post(f"/api/v1/reports/{report['id']}/{action}", json={}, headers=bearer(citizen))
        assert r.status_code == 409
    # Staff cannot change it either.
    r = await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "OPEN"}, headers=bearer(asha))
    assert r.status_code == 409


async def test_staff_reopening_restarts_the_deadline(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    report = await resolved_report(client, asha, citizen)
    r = await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "IN_PROGRESS"}, headers=bearer(asha))
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_at"] is None and body["resolution_note"] is None


# ---- deadline ------------------------------------------------------------------------


async def test_the_queue_shows_the_deadline_and_flags_overdue_work(client, monkeypatch):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    await citizen_report(client, citizen)

    row = (await client.get("/api/v1/admin/reports", headers=bearer(asha))).json()["items"][0]
    due = datetime.fromisoformat(row["due_at"])
    assert abs((due - datetime.now(timezone.utc) - timedelta(seconds=settings.ESCALATION_AFTER_SECONDS)).total_seconds()) < 60
    assert row["overdue"] is False
    assert (await client.get("/api/v1/admin/reports", params={"overdue": True}, headers=bearer(asha))).json()["items"] == []

    monkeypatch.setattr(settings, "ESCALATION_AFTER_SECONDS", 0)
    row = (await client.get("/api/v1/admin/reports", headers=bearer(asha))).json()["items"][0]
    assert row["overdue"] is True
    assert len((await client.get("/api/v1/admin/reports", params={"overdue": True}, headers=bearer(asha))).json()["items"]) == 1


async def test_an_escalated_report_leaves_the_officers_queue_and_emails_the_admin(client, monkeypatch):
    from app.events.escalation import escalate_once

    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    await citizen_report(client, citizen)
    monkeypatch.setattr(settings, "ESCALATION_AFTER_SECONDS", 0)
    assert await escalate_once() == 1

    assert (await client.get("/api/v1/admin/reports", headers=bearer(asha))).json()["items"] == []
    main = (await client.post("/api/v1/auth/login", json={"email": "main@city.example", "password": PASSWORD})).json()["access_token"]
    row = (await client.get("/api/v1/admin/reports", headers=bearer(main))).json()["items"][0]
    assert row["escalated_at"] and row["assignee_role"] == "admin" and row["due_at"] is None
    assert [m.to_email for m in await queued_emails() if m.subject.startswith("Escalated")] == ["main@city.example"]


async def test_an_existing_officer_can_be_given_a_sign_in(client):
    area = await make_area(client, "Andheri ward", ANDHERI)
    legacy = await client.post(
        "/api/v1/admin/officers", json={"name": "Old Officer", "role": "officer", "area_id": area, "telegram_chat_id": "111"}, headers=ADMIN
    )
    assert legacy.status_code == 201 and legacy.json()["email"] is None
    officer_id = legacy.json()["id"]

    # A new email needs a password; then the officer can sign in and sees their queue.
    assert (await client.put(f"/api/v1/admin/officers/{officer_id}/account", json={"email": "old@x.example"}, headers=ADMIN)).status_code == 422
    r = await client.put(
        f"/api/v1/admin/officers/{officer_id}/account", json={"email": "old@x.example", "password": PASSWORD}, headers=ADMIN
    )
    assert r.status_code == 200 and r.json()["email"] == "old@x.example"
    login = await client.post("/api/v1/auth/login", json={"email": "old@x.example", "password": PASSWORD})
    assert (await client.get("/api/v1/admin/me", headers=bearer(login.json()["access_token"]))).json()["area_name"] == "Andheri ward"

    # Replacing the account removes the old one's access; one account cannot be two officers.
    other = await client.post(
        "/api/v1/admin/officers", json={"name": "Second", "role": "officer", "area_id": area, "email": "second@x.example", "password": PASSWORD},
        headers=ADMIN,
    )
    assert other.status_code == 201
    clash = await client.put(
        f"/api/v1/admin/officers/{officer_id}/account", json={"email": "second@x.example"}, headers=ADMIN
    )
    assert clash.status_code == 409
    swap = await client.put(
        f"/api/v1/admin/officers/{officer_id}/account", json={"email": "fresh@x.example", "password": PASSWORD}, headers=ADMIN
    )
    assert swap.status_code == 200
    assert (await client.get("/api/v1/admin/reports", headers=bearer(login.json()["access_token"]))).status_code == 403
    missing = await client.put(
        "/api/v1/admin/officers/00000000-0000-0000-0000-000000000000/account", json={"email": "a@x.example"}, headers=ADMIN
    )
    assert missing.status_code == 404


async def test_make_admin_can_create_or_reset_an_account_with_a_password(client):
    from scripts.make_admin import promote

    # No account yet: with a password it is created as an administrator who can sign in.
    assert await promote("Owner@Example.org", "first-password-1") is True
    login = await client.post("/api/v1/auth/login", json={"email": "owner@example.org", "password": "first-password-1"})
    assert login.status_code == 200 and login.json()["user"]["role"] == "admin"
    assert (await client.get("/api/v1/admin/reports", headers=bearer(login.json()["access_token"]))).status_code == 200

    # An existing citizen whose password nobody knows: reset and promote in one step.
    await register(client, email="lost@example.org", password="forgotten-password")
    assert await promote("lost@example.org", "brand-new-password") is True
    old = await client.post("/api/v1/auth/login", json={"email": "lost@example.org", "password": "forgotten-password"})
    assert old.status_code == 401
    new = await client.post("/api/v1/auth/login", json={"email": "lost@example.org", "password": "brand-new-password"})
    assert new.status_code == 200 and new.json()["user"]["role"] == "admin"

    # Without a password an unknown email is still a no-op, and a known one keeps its password.
    assert await promote("nobody@example.org") is False
    assert await promote("lost@example.org") is True
    again = await client.post("/api/v1/auth/login", json={"email": "lost@example.org", "password": "brand-new-password"})
    assert again.status_code == 200


async def test_delete_user_removes_the_account_but_keeps_the_reports(client):
    from scripts.delete_user import remove

    area = await make_area(client, "Andheri ward", ANDHERI)
    await add_officer(client, "Asha", "asha@city.example", area)
    citizen = await register(client, email="gone@example.org")
    report = await citizen_report(client, citizen["access_token"])
    await register(client, email="stays@example.org")

    assert await remove("Gone@Example.org") is True
    assert await remove("gone@example.org") is False  # nothing left to delete

    login = await client.post("/api/v1/auth/login", json={"email": "gone@example.org", "password": PASSWORD})
    assert login.status_code == 404  # no account is linked to this email
    # The old token stops working, and the report is still there for everyone else.
    assert (await client.get("/api/v1/auth/me", headers=bearer(citizen["access_token"]))).status_code == 401
    assert (await client.get(f"/api/v1/reports/{report['id']}")).status_code == 200
    assert (await client.post("/api/v1/auth/login", json={"email": "stays@example.org", "password": PASSWORD})).status_code == 200

    # Deleting an officer's account leaves the officer record, just without a sign-in.
    assert await remove("asha@city.example") is True
    officers = (await client.get("/api/v1/admin/officers", headers=ADMIN)).json()
    assert [o["name"] for o in officers] == ["Asha"] and officers[0]["email"] is None


# ---- the queue on a map --------------------------------------------------------------


async def test_an_officers_map_shows_their_own_area_and_queue_only(client):
    asha, ravi = await two_cities(client)
    citizen = (await register(client))["access_token"]
    mine = await citizen_report(client, citizen)
    await citizen_report(client, citizen, latitude=28.6, longitude=77.2, city="Delhi")

    body = (await client.get("/api/v1/admin/queue-map", headers=bearer(asha))).json()
    assert [a["name"] for a in body["areas"]] == ["Andheri ward"]
    assert body["areas"][0]["geometry"]["type"] == "MultiPolygon"
    assert [r["id"] for r in body["reports"]] == [mine["id"]]
    assert body["reports"][0]["latitude"] == pytest.approx(19.076) and body["truncated"] is False

    delhi = (await client.get("/api/v1/admin/queue-map", headers=bearer(ravi))).json()
    assert [a["name"] for a in delhi["areas"]] == ["Delhi ward"] and len(delhi["reports"]) == 1


async def test_the_main_admins_map_shows_every_area_and_report(client):
    await two_cities(client)
    citizen = (await register(client))["access_token"]
    await citizen_report(client, citizen)
    await citizen_report(client, citizen, latitude=28.6, longitude=77.2, city="Delhi")
    main = (await client.post("/api/v1/auth/login", json={"email": "main@city.example", "password": PASSWORD})).json()["access_token"]

    body = (await client.get("/api/v1/admin/queue-map", headers=bearer(main))).json()
    assert sorted(a["name"] for a in body["areas"]) == ["Andheri ward", "Delhi ward"] and len(body["reports"]) == 2


async def test_the_queue_map_is_for_staff_only_and_hides_archived_reports(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    assert (await client.get("/api/v1/admin/queue-map")).status_code == 401
    assert (await client.get("/api/v1/admin/queue-map", headers=bearer(citizen))).status_code == 403

    report = await citizen_report(client, citizen)
    await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "RESOLVED"}, headers=bearer(asha))
    assert len((await client.get("/api/v1/admin/queue-map", headers=bearer(asha))).json()["reports"]) == 1  # still on the map
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE reports SET archived_at = now()"))
    assert (await client.get("/api/v1/admin/queue-map", headers=bearer(asha))).json()["reports"] == []


async def test_staff_cannot_say_me_too(client):
    asha, _ = await two_cities(client)
    citizen = (await register(client))["access_token"]
    report = await citizen_report(client, citizen)
    r = await client.post(f"/api/v1/reports/{report['id']}/support", headers=bearer(asha))
    assert r.status_code == 403
    assert (await client.get(f"/api/v1/reports/{report['id']}")).json()["affected_count"] == 1


async def test_the_queue_rows_say_where_the_problem_is_not_just_the_city(client):
    r = await client.post("/api/v1/reports/", json=sample_report(address="Balraj Khanna Marg, West Patel Nagar", landmark="near the metro", pincode="110008"))
    assert r.status_code == 201
    (row,) = (await client.get("/api/v1/admin/reports", headers=ADMIN)).json()["items"]
    assert row["address"] == "Balraj Khanna Marg, West Patel Nagar" and row["landmark"] == "near the metro"
    assert row["pincode"] == "110008" and row["city"] and row["district"] is not None
