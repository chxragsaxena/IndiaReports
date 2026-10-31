"""Sending email. One function, three ways to deliver it.

  gmail   Google's Gmail API over HTTPS. Sends from your Gmail to anyone, no domain needed, works where SMTP is blocked.
  resend  HTTPS API. Works on hosts that block outgoing SMTP (Render's free tier does).
  smtp    Any SMTP server (Gmail app password, SES, Brevo, ...).
  log     Writes the email to the server log. For development; nothing leaves the machine.

Callers never send directly: they queue a job (app/services/email_service.py) and the worker
in app/events/mailer.py calls `send_email`, retrying on failure.
"""

import asyncio
import base64
import logging
import time
import re
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class SendError(Exception):
    """Delivery failed. The worker retries later."""


def provider() -> str:
    explicit = settings.EMAIL_PROVIDER.strip().lower()
    if explicit:
        return explicit
    if settings.GMAIL_CLIENT_ID and settings.GMAIL_CLIENT_SECRET and settings.GMAIL_REFRESH_TOKEN:
        return "gmail"
    if settings.RESEND_API_KEY:
        return "resend"
    if settings.SMTP_HOST:
        return "smtp"
    return "off"


def email_enabled() -> bool:
    return provider() in ("gmail", "resend", "smtp", "log")


def clean_header(value: str) -> str:
    """One line, no control characters: user text in a subject must not inject headers."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()[:200]


def _send_smtp(to: str, subject: str, body: str) -> None:
    if not settings.SMTP_HOST:
        raise SendError("SMTP_HOST is not set")
    msg = EmailMessage()
    msg["From"] = clean_header(settings.EMAIL_FROM)
    msg["To"] = clean_header(to)
    msg["Subject"] = clean_header(subject)
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            if settings.SMTP_STARTTLS:
                server.starttls(context=ssl.create_default_context())
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise SendError(f"SMTP: {e}") from e


async def _send_resend(to: str, subject: str, body: str) -> None:
    if not settings.RESEND_API_KEY:
        raise SendError("RESEND_API_KEY is not set")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={"from": clean_header(settings.EMAIL_FROM), "to": [clean_header(to)], "subject": clean_header(subject), "text": body},
            )
    except httpx.HTTPError as e:
        raise SendError(f"Resend: {e}") from e
    if r.status_code >= 300:
        # The API explains refusals (unverified domain, bad address); keep a short excerpt.
        raise SendError(f"Resend answered {r.status_code}: {r.text[:200]}")


_gmail_token: dict = {"value": None, "expires_at": 0.0}
_gmail_lock = asyncio.Lock()


async def _google_access_token(client: httpx.AsyncClient, force: bool = False) -> str:
    """A short-lived Google access token, made from the long-lived refresh token and reused until it nearly expires."""
    async with _gmail_lock:
        if not force and _gmail_token["value"] and time.time() < _gmail_token["expires_at"] - 60:
            return _gmail_token["value"]
        r = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GMAIL_CLIENT_ID, "client_secret": settings.GMAIL_CLIENT_SECRET,
                "refresh_token": settings.GMAIL_REFRESH_TOKEN, "grant_type": "refresh_token",
            },
        )
        if r.status_code >= 300:
            hint = " The refresh token was revoked or has expired: make a new one." if "invalid_grant" in r.text else ""
            raise SendError(f"Google refused the sign-in ({r.status_code}).{hint} {r.text[:160]}")
        data = r.json()
        _gmail_token.update(value=data["access_token"], expires_at=time.time() + float(data.get("expires_in", 3600)))
        return _gmail_token["value"]


async def _send_gmail(to: str, subject: str, body: str) -> None:
    if not (settings.GMAIL_CLIENT_ID and settings.GMAIL_CLIENT_SECRET and settings.GMAIL_REFRESH_TOKEN):
        raise SendError("GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN must all be set")
    msg = EmailMessage()
    if settings.GMAIL_SENDER:
        msg["From"] = clean_header(f"IndiaReports <{settings.GMAIL_SENDER}>")
    msg["To"] = clean_header(to)
    msg["Subject"] = clean_header(subject)
    msg.set_content(body)
    payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in (1, 2):
                token = await _google_access_token(client, force=attempt == 2)
                r = await client.post(GMAIL_SEND_URL, headers={"Authorization": f"Bearer {token}"}, json=payload)
                if r.status_code != 401 or attempt == 2:  # a 401 means the cached token went stale: get a new one once
                    break
    except httpx.HTTPError as e:
        raise SendError(f"Gmail: {e}") from e
    if r.status_code >= 300:
        raise SendError(f"Gmail answered {r.status_code}: {r.text[:200]}")


async def send_email(to: str, subject: str, body: str) -> None:
    kind = provider()
    if kind == "gmail":
        await _send_gmail(to, subject, body)
    elif kind == "resend":
        await _send_resend(to, subject, body)
    elif kind == "smtp":
        await asyncio.to_thread(_send_smtp, to, subject, body)
    elif kind == "log":
        logger.info("EMAIL to=%s subject=%s\n%s", to, clean_header(subject), body)
    else:
        raise SendError("email is not configured")
