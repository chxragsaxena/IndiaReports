import uuid

from geoalchemy2 import Geometry

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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

    # Resolution. The note is written for the citizen and is shown publicly with the report.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # The reporter had the chance to check the fix; confirming lets it leave the map early.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set once a resolved report has left the public map. It stays in the database and in
    # the reporter's and officers' lists; it is just no longer drawn or counted.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # How many people this problem affects: the reporter plus everyone who said "me too".
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # Set when this looks like a copy of an older open report nearby. Staff see it; nothing is hidden.
    possible_duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )

    # What the ai-service made of the report text (language, English translation, urgency, spam
    # likelihood). Assistive and for staff only: never shown to the public or the reporter.
    triage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ReportSupporter(Base):
    """Someone who said "me too" about a report that is not their own, so it counts once per person."""

    __tablename__ = "report_supporters"

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
