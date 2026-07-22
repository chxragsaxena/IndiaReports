import uuid

from geoalchemy2 import Geometry

from sqlalchemy import Float, String, Text
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