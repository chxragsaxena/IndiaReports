"""Password reset, email verification, and deactivating an officer."""

import asyncio
import re

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from tests.test_assignment import ADMIN, make_area
from tests.test_auth import PASSWORD, bearer, register
from tests.test_staff import ANDHERI, add_officer, citizen_report, queued_emails

NEW_PASSWORD = "a brand new passphrase"


@pytest.fixture(autouse=True)
def email_on(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example")


async def last_token(path: str) -> str:
    """The secret from the newest emailed link that points at `path`."""
    for _, _, body, _ in reversed(await queued_emails()):
        found = re.search(rf"{re.escape(path)}\?token=([A-Za-z0-9_-]+)", body)
        if found:
            return found.group(1)
    raise AssertionError(f"no email contains a {path} link")


async def user_row(email: str):
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT * FROM users WHERE email = :e"), {"e": email})).mappings().one()


def resolved_mails(jobs):
    return [j for j in jobs if j.subject.startswith("Resolved")]


# ---- email verification ----------------------------------------------------------------


async def test_signing_up_sends_a_confirmation_link_and_starts_unverified(client):
    data = await register(client, "asha@example.org")
    assert data["user"]["email_verified"] is False
    (job,) = await queued_emails()
    assert job.to_email == "asha@example.org" and "https://app.example/verify-email?token=" in job.body


async def test_the_confirmation_link_verifies_once(client):
    await register(client, "asha@example.org")
    token = await last_token("/verify-email")
    assert (await client.post("/api/v1/auth/verify-email", json={"token": token})).status_code == 200
    assert (await user_row("asha@example.org"))["email_verified_at"] is not None
    assert (await client.post("/api/v1/auth/verify-email", json={"token": token})).status_code == 400  # already used


async def test_a_wrong_or_expired_link_is_refused(client):
    await register(client, "asha@example.org")
    token = await last_token("/verify-email")
    assert (await client.post("/api/v1/auth/verify-email", json={"token": "x" * 43})).status_code == 400
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE auth_tokens SET expires_at = now() - interval '1 minute'"))
    assert (await client.post("/api/v1/auth/verify-email", json={"token": token})).status_code == 400
    assert (await user_row("asha@example.org"))["email_verified_at"] is None


async def test_a_link_for_one_purpose_does_not_work_for_another(client):
    await register(client, "asha@example.org")
    token = await last_token("/verify-email")
    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD})).status_code == 400


async def test_resending_replaces_the_old_link(client):
    data = await register(client, "asha@example.org")
    first = await last_token("/verify-email")
    assert (await client.post("/api/v1/auth/resend-verification", headers=bearer(data["access_token"]))).status_code == 200
    second = await last_token("/verify-email")
    assert first != second
    assert (await client.post("/api/v1/auth/verify-email", json={"token": first})).status_code == 400
    assert (await client.post("/api/v1/auth/verify-email", json={"token": second})).status_code == 200


async def test_the_resolved_email_goes_to_the_reporter_without_any_confirmation_step(client):
    token = (await register(client, "asha@example.org"))["access_token"]
    report = await citizen_report(client, token)
    await client.patch(f"/api/v1/reports/{report['id']}/status", json={"status": "RESOLVED"}, headers=ADMIN)
    (mail,) = resolved_mails(await queued_emails())
    assert mail.to_email == "asha@example.org" and "has been marked as resolved" in mail.body


# ---- password reset --------------------------------------------------------------------


async def test_asking_to_reset_says_the_same_thing_for_unknown_addresses(client):
    await register(client, "asha@example.org")
    before = len(await queued_emails())
    unknown = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.org"})
    known = await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})
    assert unknown.status_code == known.status_code == 200 and unknown.json() == known.json()
    jobs = await queued_emails()
    assert len(jobs) == before + 1 and jobs[-1].to_email == "asha@example.org"  # only the real one got mail


async def test_a_reset_link_sets_a_new_password_once(client):
    await register(client, "asha@example.org")
    await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})
    token = await last_token("/reset-password")

    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "password": "short"})).status_code == 422
    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD})).status_code == 200

    old = await client.post("/api/v1/auth/login", json={"email": "asha@example.org", "password": PASSWORD})
    new = await client.post("/api/v1/auth/login", json={"email": "asha@example.org", "password": NEW_PASSWORD})
    assert old.status_code == 401 and new.status_code == 200
    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "password": "another one here"})).status_code == 400
    assert (await user_row("asha@example.org"))["email_verified_at"] is not None  # they read the email, so it is theirs


async def test_resetting_signs_out_older_sessions(client):
    old_session = (await register(client, "asha@example.org"))["access_token"]
    assert (await client.get("/api/v1/auth/me", headers=bearer(old_session))).status_code == 200
    await asyncio.sleep(1.1)  # tokens carry whole seconds
    await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})
    await client.post("/api/v1/auth/reset-password", json={"token": await last_token("/reset-password"), "password": NEW_PASSWORD})

    assert (await client.get("/api/v1/auth/me", headers=bearer(old_session))).status_code == 401
    fresh = (await client.post("/api/v1/auth/login", json={"email": "asha@example.org", "password": NEW_PASSWORD})).json()
    assert (await client.get("/api/v1/auth/me", headers=bearer(fresh["access_token"]))).status_code == 200


async def test_a_new_request_cancels_the_older_reset_link(client):
    await register(client, "asha@example.org")
    await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})
    first = await last_token("/reset-password")
    await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})
    second = await last_token("/reset-password")
    assert first != second
    assert (await client.post("/api/v1/auth/reset-password", json={"token": first, "password": NEW_PASSWORD})).status_code == 400
    assert (await client.post("/api/v1/auth/reset-password", json={"token": second, "password": NEW_PASSWORD})).status_code == 200


async def test_a_disabled_account_gets_no_reset_link_and_cannot_use_one(client):
    await register(client, "asha@example.org")
    await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})
    token = await last_token("/reset-password")
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET active = false"))
    count = len(await queued_emails())
    await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})
    assert len(await queued_emails()) == count
    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD})).status_code == 400


async def test_nothing_is_queued_when_email_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "off")
    await register(client, "asha@example.org")
    assert (await client.post("/api/v1/auth/forgot-password", json={"email": "asha@example.org"})).status_code == 200
    assert await queued_emails() == []


async def test_only_a_hash_of_the_link_is_stored(client):
    await register(client, "asha@example.org")
    token = await last_token("/verify-email")
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT token_hash FROM auth_tokens"))).scalar_one()
    assert stored != token and token not in stored and len(stored) == 64


# ---- deactivating an officer -------------------------------------------------------------


async def an_officer_with_reports(client):
    area = await make_area(client, "Andheri ward", ANDHERI)
    await add_officer(client, "Main Admin", "main@city.example", None, role="admin")
    token = await add_officer(client, "Asha (Mumbai)", "asha@city.example", area)
    citizen = (await register(client, "citizen@example.org"))["access_token"]
    open_one = await citizen_report(client, citizen)
    done = await citizen_report(client, citizen, title="Another pothole on the road")
    await client.patch(f"/api/v1/reports/{done['id']}/status", json={"status": "RESOLVED"}, headers=ADMIN)
    officers = (await client.get("/api/v1/admin/officers", headers=ADMIN)).json()
    officer = next(o for o in officers if o["name"] == "Asha (Mumbai)")
    return token, officer, open_one, done


async def test_deactivating_an_officer_hands_their_open_reports_to_the_main_admin(client):
    token, officer, open_one, done = await an_officer_with_reports(client)
    response = await client.post(f"/api/v1/admin/officers/{officer['id']}/deactivate", headers=ADMIN)
    assert response.status_code == 200 and response.json()["active"] is False and response.json()["reassigned"] == 1

    async with engine.connect() as conn:
        rows = {
            str(r.id): r
            for r in (await conn.execute(text("SELECT r.id, o.name AS owner FROM reports r JOIN officers o ON o.id = r.assigned_officer_id"))).all()
        }
    assert rows[open_one["id"]].owner == "Main Admin"  # an open report moves
    assert rows[done["id"]].owner == "Asha (Mumbai)"  # a finished one keeps its history

    login = await client.post("/api/v1/auth/login", json={"email": "asha@city.example", "password": PASSWORD})
    assert login.status_code == 403
    assert (await client.get("/api/v1/admin/reports", headers=bearer(token))).status_code == 401  # the old session is dead too


async def test_new_reports_skip_a_deactivated_officer_and_reactivating_brings_them_back(client):
    _, officer, _, _ = await an_officer_with_reports(client)
    await client.post(f"/api/v1/admin/officers/{officer['id']}/deactivate", headers=ADMIN)
    citizen = (await client.post("/api/v1/auth/login", json={"email": "citizen@example.org", "password": PASSWORD})).json()["access_token"]
    skipped = await citizen_report(client, citizen, title="A pothole while she is away")
    detail = (await client.get(f"/api/v1/admin/reports/{skipped['id']}", headers=ADMIN)).json()
    assert detail["assignee_name"] == "Main Admin"

    back = await client.post(f"/api/v1/admin/officers/{officer['id']}/reactivate", headers=ADMIN)
    assert back.status_code == 200 and back.json()["active"] is True
    assert (await client.post("/api/v1/auth/login", json={"email": "asha@city.example", "password": PASSWORD})).status_code == 200
    routed = await citizen_report(client, citizen, title="A pothole after she is back")
    assert (await client.get(f"/api/v1/admin/reports/{routed['id']}", headers=ADMIN)).json()["assignee_name"] == "Asha (Mumbai)"


async def test_the_main_admin_cannot_be_deactivated_and_officers_cannot_do_it(client):
    token, officer, _, _ = await an_officer_with_reports(client)
    admin = next(o for o in (await client.get("/api/v1/admin/officers", headers=ADMIN)).json() if o["role"] == "admin")
    assert (await client.post(f"/api/v1/admin/officers/{admin['id']}/deactivate", headers=ADMIN)).status_code == 409
    assert (await client.post(f"/api/v1/admin/officers/{officer['id']}/deactivate", headers=bearer(token))).status_code == 403
    assert (await client.post("/api/v1/admin/officers/00000000-0000-0000-0000-000000000000/deactivate", headers=ADMIN)).status_code == 404


async def test_the_main_admin_can_send_an_officer_a_reset_link(client):
    _, officer, _, _ = await an_officer_with_reports(client)
    response = await client.post(f"/api/v1/admin/officers/{officer['id']}/send-reset", headers=ADMIN)
    assert response.status_code == 200 and response.json()["sent_to"] == "asha@city.example"
    token = await last_token("/reset-password")
    assert (await client.post("/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD})).status_code == 200
    assert (await client.post("/api/v1/auth/login", json={"email": "asha@city.example", "password": NEW_PASSWORD})).status_code == 200


async def test_sending_a_reset_needs_an_account_and_working_email(client, monkeypatch):
    area = await make_area(client, "Andheri ward", ANDHERI)
    no_login = (
        await client.post("/api/v1/admin/officers", json={"name": "No login", "role": "officer", "area_id": area}, headers=ADMIN)
    ).json()
    assert (await client.post(f"/api/v1/admin/officers/{no_login['id']}/send-reset", headers=ADMIN)).status_code == 409


async def test_a_reset_cannot_be_sent_while_email_is_off(client, monkeypatch):
    _, officer, _, _ = await an_officer_with_reports(client)
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "off")
    assert (await client.post(f"/api/v1/admin/officers/{officer['id']}/send-reset", headers=ADMIN)).status_code == 409


async def test_staff_accounts_made_by_the_admin_start_verified(client):
    area = await make_area(client, "Andheri ward", ANDHERI)
    token = await add_officer(client, "Asha (Mumbai)", "asha@city.example", area)
    assert (await user_row("asha@city.example"))["email_verified_at"] is not None
    assert (await client.get("/api/v1/auth/me", headers=bearer(token))).json()["email_verified"] is True
