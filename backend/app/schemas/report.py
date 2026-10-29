from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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

    model_config = ConfigDict(
        from_attributes=True
    )
