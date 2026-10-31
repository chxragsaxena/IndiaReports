"""Sending through the Gmail API: sign in with the refresh token, send, reuse the token, recover when it goes stale."""

import base64
import email
import json

import httpx
import pytest

from app.core import mailer
from app.core.config import settings
from app.core.mailer import SendError


@pytest.fixture(autouse=True)
def gmail_on(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "")
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "GMAIL_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setattr(settings, "GMAIL_SENDER", "reports@gmail.example")
    mailer._gmail_token.update(value=None, expires_at=0.0)  # no token left over from another test


class FakeGoogle:
    """Stands in for Google's token and send endpoints."""

    def __init__(self, monkeypatch, token_status=200, send_statuses=(200,)):
        self.token_calls, self.sent, self.token_forms = 0, [], []
        self.token_status, self.send_statuses = token_status, list(send_statuses)

        async def post(client, url, headers=None, json=None, data=None, **_):
            request = httpx.Request("POST", url)
            if url == mailer.GOOGLE_TOKEN_URL:
                self.token_calls += 1
                self.token_forms.append(data)
                if self.token_status != 200:
                    return httpx.Response(self.token_status, text='{"error": "invalid_grant"}', request=request)
                return httpx.Response(200, json={"access_token": f"ya29.token{self.token_calls}", "expires_in": 3600}, request=request)
            assert url == mailer.GMAIL_SEND_URL
            code = self.send_statuses.pop(0) if len(self.send_statuses) > 1 else self.send_statuses[0]
            self.sent.append((headers["Authorization"], json))
            return httpx.Response(code, text="boom" if code >= 300 else "{}", request=request)

        monkeypatch.setattr(httpx.AsyncClient, "post", post)

    def message(self, index=-1):
        raw = self.sent[index][1]["raw"]
        return email.message_from_bytes(base64.urlsafe_b64decode(raw))


def test_gmail_is_chosen_when_its_three_credentials_are_set(monkeypatch):
    assert mailer.provider() == "gmail" and mailer.email_enabled()
    monkeypatch.setattr(settings, "GMAIL_REFRESH_TOKEN", None)
    assert mailer.provider() == "off"  # a partly filled setup does not half-work
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")
    assert mailer.provider() == "log"  # an explicit choice always wins


async def test_the_message_is_sent_as_the_gmail_account(monkeypatch):
    google = FakeGoogle(monkeypatch)
    await mailer.send_email("citizen@example.org", "Resolved: Pothole\nBcc: x@evil.example", "Your issue has been resolved. Thank you.")

    assert google.token_forms[0] == {
        "client_id": "client-id", "client_secret": "client-secret", "refresh_token": "refresh-token", "grant_type": "refresh_token",
    }
    authorization, payload = google.sent[0]
    assert authorization == "Bearer ya29.token1"
    message = google.message()
    assert message["To"] == "citizen@example.org" and message["From"] == "IndiaReports <reports@gmail.example>"
    assert message["Subject"] == "Resolved: Pothole Bcc: x@evil.example"  # a newline cannot add a header
    assert message["Bcc"] is None
    assert message.get_payload(decode=True).decode().strip() == "Your issue has been resolved. Thank you."


async def test_non_english_text_survives(monkeypatch):
    google = FakeGoogle(monkeypatch)
    await mailer.send_email("citizen@example.org", "समस्या हल हो गई", "आपकी शिकायत हल कर दी गई है")
    message = google.message()
    assert message.get_payload(decode=True).decode(message.get_content_charset()).strip() == "आपकी शिकायत हल कर दी गई है"


async def test_the_access_token_is_reused_between_emails(monkeypatch):
    google = FakeGoogle(monkeypatch)
    for _ in range(3):
        await mailer.send_email("citizen@example.org", "Subject", "Body")
    assert google.token_calls == 1 and len(google.sent) == 3


async def test_a_stale_token_is_replaced_once_and_the_email_still_goes(monkeypatch):
    google = FakeGoogle(monkeypatch, send_statuses=(401, 200))
    await mailer.send_email("citizen@example.org", "Subject", "Body")
    assert google.token_calls == 2
    assert [s[0] for s in google.sent] == ["Bearer ya29.token1", "Bearer ya29.token2"]


async def test_google_refusing_the_sign_in_explains_what_to_do(monkeypatch):
    FakeGoogle(monkeypatch, token_status=400)
    with pytest.raises(SendError, match="make a new one"):
        await mailer.send_email("citizen@example.org", "Subject", "Body")


async def test_a_refusal_to_send_is_an_error_the_retry_worker_can_see(monkeypatch):
    FakeGoogle(monkeypatch, send_statuses=(403,))
    with pytest.raises(SendError, match="403"):
        await mailer.send_email("citizen@example.org", "Subject", "Body")


async def test_secrets_never_appear_in_the_raw_message(monkeypatch):
    google = FakeGoogle(monkeypatch)
    await mailer.send_email("citizen@example.org", "Subject", "Body")
    everything = json.dumps(google.sent) + base64.urlsafe_b64decode(google.sent[0][1]["raw"]).decode()
    assert "client-secret" not in everything and "refresh-token" not in everything
