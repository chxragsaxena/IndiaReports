import uuid

from geoalchemy2 import Geometry

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ReportStatus
from app.models.mixins import TimestampMixin


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    title: Mapped[str] = mapped_column(String(255))

    description: Mapped[str] = mapped_column(Text())

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    latitude: Mapped[float] = mapped_column(Float)

    longitude: Mapped[float] = mapped_column(Float)

    # NEW
    geom = mapped_column(
        Geometry(
            geometry_type="POINT",
            srid=4326,
        ),
        nullable=False,
    )

    address: Mapped[str] = mapped_column(
        String(500),
        default="",
    )

    landmark: Mapped[str] = mapped_column(
        String(255),
        default="",
    )

    city: Mapped[str] = mapped_column(
        String(100),
        default="",
    )

    district: Mapped[str] = mapped_column(
        String(100),
        default="",
    )

    state: Mapped[str] = mapped_column(
        String(100),
        default="",
    )

    pincode: Mapped[str] = mapped_column(
        String(10),
        default="",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=ReportStatus.OPEN.value,
        nullable=False,
    )

    # Accountability: who is responsible, whether they acted, and whether it escalated.
    assigned_officer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("officers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Who filed it, when they were signed in. Null for anonymous reports.
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )