"""Endpoints for other services, not for browsers. They are closed unless INTERNAL_API_KEY is set."""

import hmac
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.alerts import SEVERITIES, needs_admin_attention
from app.core.config import settings
from app.db.session import get_db
from app.events.outbox import add_event
from app.models.image import ReportImage
from app.models.report import Report
from app.services.assignment_service import get_admin


def require_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    if not settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=503, detail="Service-to-service calls are not enabled.")
    if not x_internal_key or not hmac.compare_digest(x_internal_key, settings.INTERNAL_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key.")


router = APIRouter(dependencies=[Depends(require_internal_key)])


class AnalysisResult(BaseModel):
    status: Literal["done", "failed"]
    severity: Literal["low", "medium", "high", "critical"] | None = None
    analysis: dict | None = None
    provider: str | None = Field(default=None, max_length=20)
    model: str | None = Field(default=None, max_length=80)
    error: str | None = Field(default=None, max_length=500)
    attempts: int = Field(default=0, ge=0, le=100)


@router.post("/images/{image_id}/analysis")
async def record_analysis(image_id: uuid.UUID, body: AnalysisResult, db: AsyncSession = Depends(get_db)):
    """The ai-service reports what it found in a photo (or that it gave up). Safe to repeat:
    a photo that already has findings is left alone, so a redelivered message alerts nobody twice."""
    image = await db.get(ReportImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    if image.status == "done":
        return {"ok": True, "ignored": True}

    if body.status == "failed":
        image.status = "failed"
        image.attempts = body.attempts
        image.error = body.error or "Analysis failed."
        image.claimed_at = None
        await db.commit()
        return {"ok": True}

    if body.severity is None or body.analysis is None or body.severity not in SEVERITIES:
        raise HTTPException(status_code=422, detail="A finished analysis needs a severity and findings.")
    flags = body.analysis.get("flags")
    flags = [f for f in flags if isinstance(f, str)] if isinstance(flags, list) else []

    image.status = "done"
    image.attempts = body.attempts
    image.error = None
    image.claimed_at = None
    image.severity = body.severity
    image.analysis = body.analysis
    image.analysis_provider = body.provider
    image.analysis_model = body.model
    image.analyzed_at = datetime.now(timezone.utc)

    report = await db.get(Report, image.report_id)
    if report is not None and needs_admin_attention(body.severity, flags):
        admin = await get_admin(db)
        payload = {
            "report_id": str(report.id), "title": report.title, "category": report.category,
            "city": report.city, "state": report.state, "pincode": report.pincode,
            "latitude": report.latitude, "longitude": report.longitude,
            "image_id": str(image.id), "severity": body.severity,
            "summary": str(body.analysis.get("summary", ""))[:400], "provider": body.provider,
        }
        if admin is not None and body.provider != "mock":  # demo output must never page anyone
            payload["recipient"] = {
                "officer_id": str(admin.id), "name": admin.name, "role": admin.role,
                "chat_id": admin.telegram_chat_id, "ack_token": None,
            }
        add_event(db, "ReportImageAnalyzed", payload)
    await db.commit()
    return {"ok": True}


class TriageResult(BaseModel):
    status: Literal["done", "failed"]
    triage: dict | None = None
    error: str | None = Field(default=None, max_length=500)


def _bounded(value, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _clean_triage(raw: dict) -> dict | None:
    """Keep only the fields we know, bounded: this came from a model reading public text."""
    urgency = raw.get("urgency")
    if urgency not in SEVERITIES:
        return None
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "language": _bounded(raw.get("language", "English"), 40) or "English",
        "title_en": _bounded(raw.get("title_en", ""), 200),
        "description_en": _bounded(raw.get("description_en", ""), 2000),
        "suggested_category": _bounded(raw.get("suggested_category", ""), 40),
        "category_matches_report": bool(raw.get("category_matches_report", True)),
        "urgency": urgency,
        "is_spam": bool(raw.get("is_spam", False)),
        "spam_reason": _bounded(raw.get("spam_reason", ""), 200),
        "summary": _bounded(raw.get("summary", ""), 300),
        "confidence": confidence,
        "provider": _bounded(raw.get("provider", ""), 20),
        "model": _bounded(raw.get("model", ""), 80),
    }


@router.post("/reports/{report_id}/triage")
async def record_triage(report_id: uuid.UUID, body: TriageResult, db: AsyncSession = Depends(get_db)):
    """The ai-service reports what it made of a report's text. Safe to repeat: a report that
    already has a triage keeps it."""
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    if report.triaged_at is not None or body.status == "failed":
        return {"ok": True, "ignored": report.triaged_at is not None}
    triage = _clean_triage(body.triage or {})
    if triage is None:
        raise HTTPException(status_code=422, detail="A finished triage needs a valid urgency.")
    report.triage = triage
    report.triaged_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
