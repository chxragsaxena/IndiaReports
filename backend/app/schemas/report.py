from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ReportCategory, ReportStatus


class ReportCreate(BaseModel):
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

    model_config = ConfigDict(
        from_attributes=True
    )