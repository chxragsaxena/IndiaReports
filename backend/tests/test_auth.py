import os

from app.core.config import settings
from tests.conftest import sample_report

API_KEY = {"X-API-Key": os.environ["ADMIN_API_KEY"]}
PASSWORD = "correct horse battery"


async def register(client, email="asha@example.org", name="Asha Rao", password=PASSWORD):
    r = await client.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def make_admin(client, email="boss@example.org"):
    r = await client.post(
        "/api/v1/admin/users",
        json={"name": "Main Boss", "email": email, "password": PASSWORD, "role": "admin"},
        headers=API_KEY,
    )
    assert r.status_code == 201, r.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return login.json()["access_token"]


async def test_register_returns_a_citizen_session(client):
    body = await register(client)
    assert body["user"]["role"] == "citizen"
    assert body["user"]["email"] == "asha@example.org"
    me = await client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["name"] == "Asha Rao"


async def test_register_cannot_create_an_admin(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={"name": "Sneaky", "email": "sneaky@example.org", "password": PASSWORD, "role": "admin"},
    )
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "citizen"  # the extra field is ignored


async def test_duplicate_email_and_weak_password_are_rejected(client):
    await register(client)
    dup = await client.post(
        "/api/v1/auth/register", json={"name": "Again", "email": "ASHA@example.org", "password": PASSWORD}
    )
    assert dup.status_code == 409  # emails are case-insensitive
    weak = await client.post(
        "/api/v1/auth/register", json={"name": "Weak", "email": "weak@example.org", "password": "short"}
    )
    assert weak.status_code == 422


async def test_login_gives_a_clear_reason_when_it_fails(client):
    await register(client)
    ok = await client.post("/api/v1/auth/login", json={"email": "asha@example.org", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["access_token"]

    wrong_pw = await client.post("/api/v1/auth/login", json={"email": "asha@example.org", "password": "nope-nope-nope"})
    assert wrong_pw.status_code == 401
    assert "password" in wrong_pw.json()["detail"].lower()

    unknown = await client.post("/api/v1/auth/login", json={"email": "ghost@example.org", "password": PASSWORD})
    assert unknown.status_code == 404
    assert "no account" in unknown.json()["detail"].lower()
    assert "create an account" in unknown.json()["detail"].lower()


async def test_login_is_case_insensitive_on_email(client):
    await register(client)
    r = await client.post("/api/v1/auth/login", json={"email": "ASHA@Example.org", "password": PASSWORD})
    assert r.status_code == 200


async def test_disabled_account_gets_a_specific_message(client):
    from sqlalchemy import text

    from app.db.session import engine

    await register(client)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET active = false"))
    r = await client.post("/api/v1/auth/login", json={"email": "asha@example.org", "password": PASSWORD})
    assert r.status_code == 403 and "disabled" in r.json()["detail"].lower()


async def test_passwords_are_stored_hashed(client):
    from sqlalchemy import text

    from app.db.session import engine

    await register(client)
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT password_hash FROM users"))).scalar_one()
    assert PASSWORD not in stored and stored.startswith("$argon2")


async def test_bad_and_expired_tokens_are_rejected(client, monkeypatch):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=bearer("not.a.token"))).status_code == 401

    body = await register(client)
    monkeypatch.setattr(settings, "JWT_TTL_SECONDS", -10)
    expired = (await client.post("/api/v1/auth/login", json={"email": "asha@example.org", "password": PASSWORD})).json()
    assert (await client.get("/api/v1/auth/me", headers=bearer(expired["access_token"]))).status_code == 401
    monkeypatch.undo()
    assert (await client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))).status_code == 200


async def test_citizens_cannot_use_admin_endpoints_but_admins_can(client):
    citizen = (await register(client))["access_token"]
    admin = await make_admin(client)

    assert (await client.get("/api/v1/admin/reports", headers=bearer(citizen))).status_code == 403
    # A citizen who also sends the service key is still refused: the signed-in identity wins.
    assert (await client.get("/api/v1/admin/reports", headers=bearer(citizen) | API_KEY)).status_code == 403
    assert (await client.get("/api/v1/admin/reports")).status_code == 401
    assert (await client.get("/api/v1/admin/reports", headers=bearer(admin))).status_code == 200


async def test_admin_token_can_change_report_status(client):
    admin = await make_admin(client)
    created = (await client.post("/api/v1/reports/", json=sample_report())).json()
    r = await client.patch(
        f"/api/v1/reports/{created['id']}/status", json={"status": "RESOLVED"}, headers=bearer(admin)
    )
    assert r.status_code == 200 and r.json()["status"] == "RESOLVED"

    citizen = (await register(client))["access_token"]
    denied = await client.patch(
        f"/api/v1/reports/{created['id']}/status", json={"status": "OPEN"}, headers=bearer(citizen)
    )
    assert denied.status_code == 403


async def test_deactivated_admin_loses_access_immediately(client):
    from sqlalchemy import text

    from app.db.session import engine

    admin = await make_admin(client)
    assert (await client.get("/api/v1/admin/reports", headers=bearer(admin))).status_code == 200
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET active = false"))
    assert (await client.get("/api/v1/admin/reports", headers=bearer(admin))).status_code == 401


async def test_my_reports_are_scoped_to_the_signed_in_citizen(client):
    asha = (await register(client, "asha@example.org", "Asha Rao"))["access_token"]
    ravi = (await register(client, "ravi@example.org", "Ravi Kumar"))["access_token"]

    await client.post("/api/v1/reports/", json=sample_report(title="Asha pothole"), headers=bearer(asha))
    await client.post("/api/v1/reports/", json=sample_report(title="Ravi garbage"), headers=bearer(ravi))
    await client.post("/api/v1/reports/", json=sample_report(title="Anonymous leak"))

    mine = (await client.get("/api/v1/me/reports", headers=bearer(asha))).json()
    assert [r["title"] for r in mine] == ["Asha pothole"]
    assert (await client.get("/api/v1/me/reports")).status_code == 401


async def test_requiring_login_to_report(client, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_LOGIN_TO_REPORT", True)
    anonymous = await client.post("/api/v1/reports/", json=sample_report())
    assert anonymous.status_code == 401

    token = (await register(client))["access_token"]
    signed_in = await client.post("/api/v1/reports/", json=sample_report(), headers=bearer(token))
    assert signed_in.status_code == 201


async def test_invalid_token_on_report_is_an_error_not_anonymous(client):
    r = await client.post("/api/v1/reports/", json=sample_report(), headers=bearer("garbage"))
    assert r.status_code == 401
