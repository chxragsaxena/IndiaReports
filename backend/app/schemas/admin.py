import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

_CHAT_ID = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")


class AreaCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    # GeoJSON geometry, Polygon or MultiPolygon, WGS84 [lng, lat].
    geometry: dict


class AreaResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime | None = None


class OfficerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    role: Literal["officer", "admin"] = "officer"
    # Optional: an officer can work only through the website and email.
    telegram_chat_id: str | None = None
    area_id: UUID | None = None
    # The officer's sign-in account. If this email already has an account it is linked (and
    # made an officer); otherwise a password is required and the account is created.
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("telegram_chat_id")
    @classmethod
    def valid_chat_id(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _CHAT_ID.match(v):
            raise ValueError("must be a numeric Telegram chat id or @channelname")
        return v


class OfficerAccount(BaseModel):
    email: EmailStr
    # Only needed when this email has no account yet.
    password: str | None = Field(default=None, min_length=8, max_length=128)


class OfficerResponse(BaseModel):
    id: UUID
    name: str
    role: str
    telegram_chat_id: str | None = None
    area_id: UUID | None = None
    area_name: str | None = None
    email: str | None = None  # the account they sign in with
    active: bool


class StaffProfile(BaseModel):
    """Who the signed-in staff member is, so the page can show their scope."""

    is_main: bool
    name: str | None = None
    area_id: UUID | None = None
    area_name: str | None = None
    # How long an officer has to resolve a report, and how long a resolved one stays on the map.
    resolve_within_seconds: int
    resolved_visible_seconds: int


class AcknowledgeRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class AdminReportRow(BaseModel):
    id: UUID
    title: str
    category: str
    status: str
    city: str
    state: str
    latitude: float
    longitude: float
    created_at: datetime | None = None
    assigned_at: datetime | None = None
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    archived_at: datetime | None = None
    resolution_note: str | None = None
    # When it must be resolved by before it escalates (null once resolved or escalated).
    due_at: datetime | None = None
    overdue: bool = False
    assignee_name: str | None = None
    assignee_role: str | None = None
    image_count: int = 0
    ai_severity: str | None = None  # the most serious finding across the photos
    ai_pending: bool = False  # some photos are still waiting for analysis


class AdminReportPage(BaseModel):
    items: list[AdminReportRow]
    # Pass as `before` to get the next (older) page; null when there is no more.
    next_before: datetime | None = None
