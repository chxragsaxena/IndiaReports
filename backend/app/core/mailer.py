"""Sending email. One function, three ways to deliver it.

  resend  HTTPS API. Works on hosts that block outgoing SMTP (Render's free tier does).
  smtp    Any SMTP server (Gmail app password, SES, Brevo, ...).
  log     Writes the email to the server log. For development; nothing leaves the machine.

Callers never send directly: they queue a job (app/services/email_service.py) and the worker
in app/events/mailer.py calls `send_email`, retrying on failure.
"""

import asyncio
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class SendError(Exception):
    """Delivery failed. The worker retries later."""


def provider() -> str:
    explicit = settings.EMAIL_PROVIDER.strip().lower()
    if explicit:
        return explicit
    if settings.RESEND_API_KEY:
        return "resend"
    if settings.SMTP_HOST:
        return "smtp"
    return "off"


def email_enabled() -> bool:
    return provider() in ("resend", "smtp", "log")


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


async def send_email(to: str, subject: str, body: str) -> None:
    kind = provider()
    if kind == "resend":
        await _send_resend(to, subject, body)
    elif kind == "smtp":
        await asyncio.to_thread(_send_smtp, to, subject, body)
    elif kind == "log":
        logger.info("EMAIL to=%s subject=%s\n%s", to, clean_header(subject), body)
    else:
        raise SendError("email is not configured")
