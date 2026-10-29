"""Sending queued email: retries, giving up, and the delivery providers."""

import smtplib
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from app.core import mailer
from app.core.config import settings
from app.core.mailer import SendError
from app.db.session import AsyncSessionLocal, engine
from app.events.mailer import retry_delay, send_pending_once
from app.services.email_service import queue_email


@pytest.fixture(autouse=True)
def email_on(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")


async def queue(to="a@x.example", key="k1", subject="Hello", body="Body"):
    async with AsyncSessionLocal() as db:
        await queue_email(db, to, subject, body, key)
        await db.commit()


async def job():
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT * FROM email_jobs ORDER BY id"))).mappings().all()


async def test_a_queued_email_is_sent_once(client):
    await queue()
    sent = []

    async def sender(to, subject, body):
        sent.append((to, subject, body))

    assert await send_pending_once(sender) == 1
    assert sent == [("a@x.example", "Hello", "Body")]
    assert (await job())[0]["sent_at"] is not None
    assert await send_pending_once(sender) == 0  # never twice
    assert len(sent) == 1


async def test_the_same_notice_is_queued_only_once(client):
    await queue(key="resolved:1")
    await queue(key="resolved:1")
    await queue(key="resolved:2")
    assert len(await job()) == 2


async def test_nothing_is_queued_without_an_address_or_when_email_is_off(client, monkeypatch):
    await queue(to=None)
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "off")
    await queue(key="k2")
    assert await job() == []


async def test_a_failed_send_is_retried_later_and_then_succeeds(client):
    await queue()

    async def failing(*_):
        raise SendError("provider down")

    assert await send_pending_once(failing) == 0
    row = (await job())[0]
    assert row["attempts"] == 1 and row["sent_at"] is None and "provider down" in row["last_error"]
    assert row["next_attempt_at"] > datetime.now(timezone.utc)  # backs off

    # Not due yet: a healthy provider is not even tried.
    called = []

    async def healthy(*args):
        called.append(args)

    assert await send_pending_once(healthy) == 0 and called == []

    async with engine.begin() as conn:
        await conn.execute(text("UPDATE email_jobs SET next_attempt_at = now() - interval '1 second'"))
    assert await send_pending_once(healthy) == 1
    assert (await job())[0]["last_error"] is None


async def test_the_worker_gives_up_after_the_attempt_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_MAX_ATTEMPTS", 2)
    await queue()

    async def failing(*_):
        raise SendError("nope")

    for _ in range(3):
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE email_jobs SET next_attempt_at = now() - interval '1 second'"))
        await send_pending_once(failing)
    assert (await job())[0]["attempts"] == 2  # stopped trying


def test_retry_delay_grows_and_is_capped():
    assert retry_delay(1) == timedelta(minutes=1)
    assert retry_delay(2) == timedelta(minutes=2)
    assert retry_delay(3) == timedelta(minutes=4)
    assert retry_delay(50) == timedelta(hours=6)


# ---- providers -------------------------------------------------------------------------


def test_provider_choice(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "")
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert mailer.provider() == "off" and not mailer.email_enabled()
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    assert mailer.provider() == "smtp"
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_x")
    assert mailer.provider() == "resend"  # an HTTPS API wins: it works where SMTP is blocked
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")
    assert mailer.provider() == "log"


def test_user_text_cannot_inject_email_headers():
    assert mailer.clean_header("Hi\r\nBcc: attacker@x.example") == "Hi Bcc: attacker@x.example"
    assert "\n" not in mailer.clean_header("a\nb")


async def test_resend_request_shape_and_errors(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_secret")
    seen = {}

    async def fake_post(self, url, headers=None, json=None, **_):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(status.get("code", 200), text="nope", request=httpx.Request("POST", url))

    status = {}
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await mailer.send_email("to@x.example", "Subject\nInjected", "Hello")
    assert seen["url"] == mailer.RESEND_URL
    assert seen["headers"]["Authorization"] == "Bearer re_secret"
    assert seen["json"]["to"] == ["to@x.example"] and seen["json"]["subject"] == "Subject Injected"
    assert seen["json"]["text"] == "Hello"

    status["code"] = 403
    with pytest.raises(SendError, match="403"):
        await mailer.send_email("to@x.example", "S", "B")


async def test_smtp_delivery(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pw")
    log = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            log["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self, context=None):
            log["tls"] = True

        def login(self, user, password):
            log["login"] = (user, password)

        def send_message(self, msg):
            log["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    await mailer.send_email("to@x.example", "Resolved: pothole", "Fixed.")
    assert log["server"] == ("smtp.example", 587) and log["tls"] and log["login"] == ("user", "pw")
    assert log["msg"]["To"] == "to@x.example" and log["msg"]["Subject"] == "Resolved: pothole"
    assert "Fixed." in log["msg"].get_content()

    class Broken(FakeSMTP):
        def send_message(self, msg):
            raise smtplib.SMTPException("mailbox full")

    monkeypatch.setattr(smtplib, "SMTP", Broken)
    with pytest.raises(SendError, match="mailbox full"):
        await mailer.send_email("to@x.example", "S", "B")


async def test_sending_while_unconfigured_fails_cleanly(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "off")
    with pytest.raises(SendError):
        await mailer.send_email("to@x.example", "S", "B")
