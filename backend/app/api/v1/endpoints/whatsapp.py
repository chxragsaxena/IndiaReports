"""Reporting through WhatsApp (Twilio). A person sends the problem as text or a voice note and shares their
location; the report is filed like any other. Nothing is stored about them: the phone number is only hashed
into a short-lived conversation key and a daily counter. Staff see the report as an anonymous one.

Twilio posts every incoming message here and shows the reply we return as TwiML, so no outbound credentials
are needed to talk. (Telling the person later that it was fixed would need the WhatsApp sender API: not built.)
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audio import VOICE_PLACEHOLDER, AudioRejected, sniff
from app.core.config import settings
from app.core.redis import get_redis
from app.core.storage import get_store
from app.db.session import get_db
from app.events.outbox import add_event
from app.models.area import Officer
from app.models.enums import ReportCategory
from app.models.report import Report
from app.models.voice import ReportVoiceNote
from app.schemas.report import ReportCreate
from app.services.geocode import reverse_geocode
from app.services.report_service import ReportService

logger = logging.getLogger(__name__)
router = APIRouter()

STATE_TTL = 15 * 60  # a half-finished report is forgotten after 15 minutes
HELP_WORDS = {"hi", "hello", "hey", "help", "start", "menu", "namaste", "नमस्ते", "हेलो", "हाय"}
CANCEL_WORDS = {"cancel", "reset", "clear", "रद्द"}

HELP = (
    "Welcome to IndiaReports.\n"
    "To report a civic problem (pothole, garbage, broken street light...):\n"
    "1. Send a message or a voice note describing it.\n"
    "2. Share the location: tap the + (attach) button, choose Location, then Send your current location.\n"
    "Send CANCEL to start again."
)


def twiml(text: str) -> Response:
    return Response(content=f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{escape(text)}</Message></Response>", media_type="application/xml")


def valid_signature(url: str, params: dict[str, str], signature: str | None, token: str) -> bool:
    """Twilio signs the full URL followed by every posted field (sorted by name) with the account's auth token."""
    if not signature:
        return False
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


def _who(sender: str) -> str:
    """A hash of the phone number: enough to keep one conversation apart from another, useless to read."""
    return hashlib.sha256(f"indiareports/whatsapp/{sender}".encode()).hexdigest()[:32]


async def _load(redis, who: str) -> dict:
    raw = await redis.get(f"wa:state:{who}")
    return json.loads(raw) if raw else {}


async def _save(redis, who: str, state: dict) -> None:
    await redis.set(f"wa:state:{who}", json.dumps(state), ex=STATE_TTL)


async def _within_daily_limit(redis, who: str) -> bool:
    key = f"wa:cap:{who}:{datetime.now(timezone.utc):%Y%m%d}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 2 * 24 * 3600)
    return count <= settings.WHATSAPP_REPORTS_PER_DAY


async def _fetch_voice(url: str) -> bytes | None:
    """Download the voice note from Twilio. Only Twilio's own https addresses are fetched, and no more than the voice size limit."""
    host = (httpx.URL(url).host or "") if url else ""
    if not url.startswith("https://") or not (host == "twilio.com" or host.endswith(".twilio.com")):
        return None
    auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN else None
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            async with client.stream("GET", url, auth=auth) as response:
                if response.status_code != 200:
                    return None
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > settings.MAX_VOICE_BYTES:
                        return None
                return bytes(data)
    except httpx.HTTPError:
        return None


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


async def _file_report(db: AsyncSession, state: dict, voice: bytes | None) -> tuple[Report, bool]:
    """The filed report, and whether a voice note was kept with it."""
    text = (state.get("text") or "").strip()
    lat, lng = state["lat"], state["lng"]
    place = await reverse_geocode(lat, lng) if settings.WHATSAPP_GEOCODE else {"address": "", "city": "", "district": "", "state": "", "pincode": ""}
    report = await ReportService.create_report(
        db,
        ReportCreate(
            title=(text[:60].strip() if len(text) >= 3 else "Voice report via WhatsApp"),
            description=text or VOICE_PLACEHOLDER,
            category=ReportCategory.OTHER,  # the text triage suggests a better one for staff
            latitude=lat, longitude=lng,
            address=(state.get("address") or place["address"])[:500], landmark="",
            city=place["city"], district=place["district"], state=place["state"], pincode=place["pincode"],
        ),
        reporter_id=None,
    )
    store = get_store()
    if voice is not None and store is not None:
        kind = sniff(voice)
        note_id = uuid.uuid4()
        key = f"reports/{report.id}/voice-{note_id}.{kind.extension}"
        await store.put(key, voice, kind.content_type)
        db.add(ReportVoiceNote(id=note_id, report_id=report.id, uploader_id=None, storage_key=key, content_type=kind.content_type, size_bytes=len(voice)))
        add_event(db, "VoiceNoteUploaded", {
            "voice_id": str(note_id), "report_id": str(report.id), "storage_key": key,
            "content_type": kind.content_type, "size_bytes": len(voice), "language": None,
        })
        await db.commit()
        return report, True
    return report, False


async def converse(form: dict[str, str], redis, db: AsyncSession) -> str:
    """One incoming message in, the reply out."""
    who = _who(form.get("From", ""))
    body = " ".join((form.get("Body") or "").split())
    lowered = body.lower()
    lat, lng = _float(form.get("Latitude")), _float(form.get("Longitude"))
    audio_url = form.get("MediaUrl0") if int(form.get("NumMedia") or 0) > 0 and (form.get("MediaContentType0") or "").startswith("audio/") else None

    if lowered in CANCEL_WORDS:
        await redis.delete(f"wa:state:{who}")
        return "Cancelled. Send HI whenever you want to report a problem."

    state = await _load(redis, who)
    if lowered in HELP_WORDS and not state:
        return HELP

    if lat is not None and lng is not None:
        if not (6.0 <= lat <= 38.0 and 68.0 <= lng <= 98.0):
            return "Reports can only be filed for locations in India. Please share the location of the problem again."
        state.update(lat=lat, lng=lng, address=" ".join((form.get("Address") or form.get("Label") or "").split())[:500])
    if audio_url:
        state["audio_url"] = audio_url
    if body and lowered not in HELP_WORDS:
        if len(body) < 3:
            return "Please describe the problem in a few words, or send a voice note."
        state["text"] = body[:1000]

    has_place = "lat" in state
    has_story = bool(state.get("text") or state.get("audio_url"))
    if not (has_place and has_story):
        await _save(redis, who, state)
        if has_place:
            return "Got the location. Now describe the problem in a message or a voice note."
        if has_story:
            return "Thanks. Now share the location of the problem: tap the + button, choose Location, then Send your current location."
        return HELP

    # Both parts are here: file it.
    voice = None
    if state.get("audio_url"):
        voice = await _fetch_voice(state["audio_url"])
        if voice is not None:
            try:
                sniff(voice)
            except AudioRejected:
                voice = None
        if voice is None and not state.get("text"):
            state.pop("audio_url", None)
            await _save(redis, who, state)
            return "Sorry, I could not read your voice note. Please type the problem instead."
        if voice is not None and get_store() is None and not state.get("text"):
            state.pop("audio_url", None)
            await _save(redis, who, state)
            return "Voice notes are not available right now. Please type the problem instead."

    if not await _within_daily_limit(redis, who):
        await redis.delete(f"wa:state:{who}")
        return "You have reached today's limit of reports from this number. Please try again tomorrow."

    report, kept_voice = await _file_report(db, state, voice)
    await redis.delete(f"wa:state:{who}")
    assignee = await db.get(Officer, report.assigned_officer_id) if report.assigned_officer_id else None
    link = f"{settings.PUBLIC_APP_URL.rstrip('/')}/?report={report.id}&lat={report.latitude}&lng={report.longitude}&z=16" if settings.PUBLIC_APP_URL else ""
    return (
        f"Your report is filed. Reference: {str(report.id)[:8].upper()}.\n"
        + (f"It has gone to {assignee.name}." if assignee else "It is now on the public map.")
        + (" Your voice note is being turned into text for the officer." if kept_voice else "")
        + (f"\nSee it on the map: {link}" if link else "")
    )


@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Twilio calls this for every WhatsApp message sent to our number."""
    if not settings.TWILIO_AUTH_TOKEN or not settings.WHATSAPP_WEBHOOK_URL:
        raise HTTPException(status_code=503, detail="WhatsApp reporting is not set up.")
    form = {k: str(v) for k, v in (await request.form()).items()}
    if not valid_signature(settings.WHATSAPP_WEBHOOK_URL, form, request.headers.get("x-twilio-signature"), settings.TWILIO_AUTH_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid signature.")

    redis = get_redis()
    if redis is None:
        return twiml("Sorry, reporting by WhatsApp is not available right now. Please use the website.")
    try:
        return twiml(await converse(form, redis, db))
    except Exception:  # never leave the person without an answer, and never show them an error page
        logger.exception("whatsapp message failed")
        await db.rollback()
        return twiml("Sorry, something went wrong on our side. Please try again in a minute, or use the website.")
