import math
import uuid
from datetime import datetime, timezone

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import cache_get, cache_set
from app.events.outbox import (
    add_event,
    report_created_payload,
    status_changed_payload,
)
from app.models.enums import ReportStatus
from app.models.report import Report
from app.schemas.report import ReportCreate, ReportResponse
from app.services.assignment_service import find_assignee, recipient_for


def _grid_size_for_zoom(zoom: int) -> float:
    if zoom <= 3:
        return 2.0
    if zoom == 4:
        return 1.2
    if zoom == 5:
        return 0.7
    if zoom == 6:
        return 0.35
    if zoom == 7:
        return 0.18
    return 0.1


def _viewport_filter(min_lat, max_lat, min_lng, max_lng):
    return func.ST_Intersects(
        Report.geom,
        func.ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326),
    )


class ReportService:

    @staticmethod
    async def create_report(
        db: AsyncSession,
        report: ReportCreate,
    ) -> Report:

        db_report = Report(
            **report.model_dump(),
            geom=WKTElement(
                f"POINT({report.longitude} {report.latitude})",
                srid=4326,
            ),
        )
        db.add(db_report)

        # Flush so server-side defaults (created_at) are available for the event,
        # then write the event in the SAME transaction as the report.
        await db.flush()
        await db.refresh(db_report)

        # Route to the officer whose area contains the point (admin if none does).
        recipient = None
        assignee = await find_assignee(db, report.latitude, report.longitude)
        if assignee is not None:
            db_report.assigned_officer_id = assignee.id
            db_report.assigned_at = datetime.now(timezone.utc)
            recipient = recipient_for(db_report, assignee)

        add_event(db, "ReportCreated", report_created_payload(db_report, recipient))

        await db.commit()
        await db.refresh(db_report)

        return db_report

    @staticmethod
    async def get_report(db: AsyncSession, report_id: uuid.UUID) -> Report | None:
        return await db.get(Report, report_id)

    @staticmethod
    async def update_status(
        db: AsyncSession,
        report_id: uuid.UUID,
        new_status: ReportStatus,
    ) -> Report | None:
        result = await db.execute(
            select(Report).where(Report.id == report_id).with_for_update()
        )
        report = result.scalar_one_or_none()
        if report is None:
            return None

        old_status = report.status
        if old_status == new_status.value:
            return report  # idempotent: no change, no event

        report.status = new_status.value
        changed_at = datetime.now(timezone.utc)
        if report.acknowledged_at is None and new_status != ReportStatus.OPEN:
            report.acknowledged_at = changed_at  # someone acted on it: nothing to escalate
        add_event(db, "ReportStatusChanged", status_changed_payload(report, old_status, changed_at))

        await db.commit()
        await db.refresh(report)
        return report

    @staticmethod
    async def get_reports(
        db: AsyncSession,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lng: float | None = None,
        max_lng: float | None = None,
        status: str | None = None,
        category: str | None = None,
        limit: int | None = None,
    ):
        # Never return an unbounded result set.
        limit = min(limit or settings.MAX_REPORTS_PER_QUERY, settings.MAX_REPORTS_PER_QUERY)

        query = select(Report)

        if None not in (min_lat, max_lat, min_lng, max_lng):
            query = query.where(_viewport_filter(min_lat, max_lat, min_lng, max_lng))

        if status:
            query = query.where(Report.status == status)

        if category:
            query = query.where(Report.category == category)

        query = query.order_by(Report.created_at.desc()).limit(limit)

        result = await db.execute(query)

        return result.scalars().all()

    @staticmethod
    async def get_dashboard(db: AsyncSession):
        cache_key = "cache:dashboard:v1"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        status_rows = await db.execute(
            select(Report.status, func.count()).group_by(Report.status)
        )
        by_status = {status: count for status, count in status_rows.all()}

        category_rows = await db.execute(
            select(Report.category, func.count()).group_by(Report.category)
        )
        by_category = {category: count for category, count in category_rows.all()}

        recent_rows = await db.execute(
            select(Report).order_by(Report.created_at.desc()).limit(5)
        )
        recent = [
            ReportResponse.model_validate(r).model_dump(mode="json")
            for r in recent_rows.scalars().all()
        ]

        data = {
            "total_reports": sum(by_status.values()),
            "open_reports": by_status.get(ReportStatus.OPEN.value, 0),
            "in_progress_reports": by_status.get(ReportStatus.IN_PROGRESS.value, 0),
            "resolved_reports": by_status.get(ReportStatus.RESOLVED.value, 0),
            "by_category": by_category,
            "recent_reports": recent,
        }

        await cache_set(cache_key, data, settings.DASHBOARD_CACHE_TTL_SECONDS)
        return data

    @staticmethod
    async def get_clusters(
        db: AsyncSession,
        min_lat: float,
        max_lat: float,
        min_lng: float,
        max_lng: float,
        zoom: int,
        status: str | None = None,
        category: str | None = None,
    ):
        """Grid-clustered reports for the viewport.

        The viewport is snapped outward to the cluster grid so many users panning
        around the same area share one cache entry (and one database query)."""

        grid_size = _grid_size_for_zoom(zoom)

        min_lat = math.floor(min_lat / grid_size) * grid_size
        max_lat = math.ceil(max_lat / grid_size) * grid_size
        min_lng = math.floor(min_lng / grid_size) * grid_size
        max_lng = math.ceil(max_lng / grid_size) * grid_size

        cache_key = (
            f"cache:clusters:v1:{zoom}:{min_lat:.3f}:{max_lat:.3f}:"
            f"{min_lng:.3f}:{max_lng:.3f}:{status or '-'}:{category or '-'}"
        )
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        query = select(
            func.avg(Report.latitude).label("latitude"),
            func.avg(Report.longitude).label("longitude"),
            func.count().label("count"),
        ).where(_viewport_filter(min_lat, max_lat, min_lng, max_lng))

        if status:
            query = query.where(Report.status == status)

        if category:
            query = query.where(Report.category == category)

        query = query.group_by(
            func.floor(Report.latitude / grid_size),
            func.floor(Report.longitude / grid_size),
        )

        result = await db.execute(query)

        clusters = [
            {
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "count": int(row["count"]),
            }
            for row in result.mappings().all()
        ]

        await cache_set(cache_key, clusters, settings.CLUSTER_CACHE_TTL_SECONDS)
        return clusters
