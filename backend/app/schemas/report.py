from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.config import settings
from app.models.enums import ReportCategory, ReportStatus


class ReportCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=3, max_length=5000)
    category: ReportCategory

    latitude: float = Field(ge=6.0, le=38.0)
    longitude: float = Field(ge=68.0, le=98.0)

    address: str = Field(max_length=500)
    landmark: str = Field(max_length=255)
    city: str = Field(max_length=100)
    district: str = Field(max_length=100)
    state: str = Field(max_length=100)
    pincode: str = Field(max_length=10)


class ReportStatusUpdate(BaseModel):
    status: ReportStatus
    # What was done, written for the citizen. Shown publicly and emailed when resolving.
    note: str | None = Field(default=None, max_length=1000)


class SimilarReport(BaseModel):
    """An open report nearby that looks like the same problem (public fields only)."""

    id: UUID
    title: str
    category: ReportCategory
    status: ReportStatus
    distance_m: int
    affected_count: int
    latitude: float
    longitude: float
    created_at: datetime | None = None


class SupportResponse(BaseModel):
    affected_count: int
    added: bool  # false when this person had already said so, or reported it themselves


class ReopenRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReportResponse(BaseModel):
    id: UUID

    title: str
    description: str

    category: ReportCategory

    latitude: float
    longitude: float

    address: str
    landmark: str
    city: str
    district: str
    state: str
    pincode: str

    status: ReportStatus

    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Accountability trail (officer identity and contact details are not exposed).
    assigned_at: datetime | None = None
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None

    # Resolution. Once a report is resolved the reporter has until it leaves the map
    # (archived_at) to confirm the fix or reopen it.
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    confirmed_at: datetime | None = None
    archived_at: datetime | None = None

    # How many people this affects: the reporter plus everyone who said "me too".
    affected_count: int = 1

    @computed_field
    @property
    def leaves_map_at(self) -> datetime | None:
        """When a resolved report stops being drawn on the public map (the end of the
        reporter's window to check it). Null if it is not resolved or already gone."""
        if self.status != ReportStatus.RESOLVED or self.archived_at is not None or self.resolved_at is None:
            return None
        return self.resolved_at + timedelta(seconds=settings.RESOLVED_VISIBLE_SECONDS)

    model_config = ConfigDict(
        from_attributes=True
    )
