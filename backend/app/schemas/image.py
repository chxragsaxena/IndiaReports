from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ImageUploadResponse(BaseModel):
    id: UUID
    width: int
    height: int


class AdminImage(BaseModel):
    id: UUID
    url: str  # short-lived link to the photo
    width: int
    height: int
    status: str  # pending | analyzing | done | failed
    severity: str | None = None
    findings: dict | None = None
    kind: str = "report"  # report = photo of the problem, fix = photo of the repair
    verification: dict | None = None  # for a repair photo: the before/after verdict
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    analyzed_at: datetime | None = None


class AdminReportDetail(BaseModel):
    id: UUID
    title: str
    description: str
    category: str
    status: str
    address: str
    city: str
    district: str
    state: str
    pincode: str
    latitude: float
    longitude: float
    created_at: datetime | None = None
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    assignee_name: str | None = None
    images: list[AdminImage]
    analysis_enabled: bool
    triage: dict | None = None  # what the ai-service made of the text; staff only
    affected_count: int = 1
    possible_duplicate: dict | None = None  # {id, title, status} of the older report this may copy
