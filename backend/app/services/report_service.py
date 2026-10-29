import math
import uuid
from datetime import datetime, timezone

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cached_json
from app.core.config import settings
from app.events.outbox import (
    add_event,
    report_created_payload,
    status_changed_payload,
)
from app.models.enums import ReportStatus
from app.models.report import Report
from app.schemas.report import ReportCreate, ReportResponse
from app.services.assignment_service import find_assignee, recipient_for
from app.services.cell_service import TOTALS_LEVEL, cell_of, grid_for_zoom, level_for_zoom

# Pins are fetched for the viewport snapped outward to this grid, so users looking at
# the same area share one database query and one cache entry.
PIN_SNAP_DEGREES = 0.05
PIN_CACHE_TTL_SECONDS = 10


def _viewport_filter(min_lat, max_lat, min_lng, max_lng):
    return func.ST_Intersects(
        Report.geom,
        func.ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326),
    )


def _snap_out(min_v: float, max_v: float, grid: float) -> tuple[float, float]:
    return math.floor(min_v / grid) * grid, math.ceil(max_v / grid) * grid


class ReportService:

    @staticmethod
    async def create_report(
        db: AsyncSession,
        report: ReportCreate,
    ) -> Report:

        # Decide everything up front and set every column in Python, so the report is
        # one INSERT with no read-back: fewer database round trips per write, and no
        # UPDATE for the assignment.
        now = datetime.now(timezone.utc)

        # Route to the officer whose area contains the point (admin if none does).
        assignee = await find_assignee(db, report.latitude, report.longitude)

        db_report = Report(
            **report.model_dump(),
            id=uuid.uuid4(),
            status=ReportStatus.OPEN.value,
            created_at=now,
            updated_at=now,
            assigned_officer_id=assignee.id if assignee else None,
            assigned_at=now if assignee else None,
            acknowledged_at=None,
            escalated_at=None,
            geom=WKTElement(
                f"POINT({report.longitude} {report.latitude})",
                srid=4326,
            ),
        )
        recipient = recipient_for(db_report, assignee) if assignee else None

        db.add(db_report)

        # The event is written in the SAME transaction as the report. The map/dashboard
        # rollup is updated from it by a background applier (app/events/rollup.py), not
        # here: updating shared cell rows in every request would make all writes in one
        # area queue on the same locks.
        add_event(db, "ReportCreated", report_created_payload(db_report, recipient))

        await db.commit()

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
        """Full report records (used by integrations). The map uses get_pins instead."""
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
    async def get_pins(
        db: AsyncSession,
        min_lat: float,
        max_lat: float,
        min_lng: float,
        max_lng: float,
        status: str | None = None,
        category: str | None = None,
    ) -> str:
        """Lightweight map pins (id, status, position) as ready JSON. Only what the map
        draws; title, category and the rest are fetched by id when a pin is opened."""
        min_lat, max_lat = _snap_out(min_lat, max_lat, PIN_SNAP_DEGREES)
        min_lng, max_lng = _snap_out(min_lng, max_lng, PIN_SNAP_DEGREES)
        cap = settings.MAX_PINS_PER_QUERY

        key = (
            f"cache:pins:v1:{min_lat:.3f}:{max_lat:.3f}:{min_lng:.3f}:{max_lng:.3f}:"
            f"{status or '-'}:{category or '-'}"
        )

        async def compute():
            query = select(
                Report.id, Report.status, Report.latitude, Report.longitude,
            ).where(_viewport_filter(min_lat, max_lat, min_lng, max_lng))
            if status:
                query = query.where(Report.status == status)
            if category:
                query = query.where(Report.category == category)
            rows = (await db.execute(query.order_by(Report.created_at.desc()).limit(cap + 1))).all()
            return {
                "truncated": len(rows) > cap,
                "pins": [
                    {"id": str(r.id), "status": r.status, "latitude": r.latitude, "longitude": r.longitude}
                    for r in rows[:cap]
                ],
            }

        return await cached_json(key, PIN_CACHE_TTL_SECONDS, compute)

    @staticmethod
    async def get_dashboard(db: AsyncSession) -> str:
        """Counts come from the grid rollup (a few thousand rows), never from a scan
        of the reports table, so this costs the same at 1 thousand or 100 million."""

        async def compute():
            rows = (
                await db.execute(
                    text(
                        "SELECT status, category, sum(cnt)::bigint AS n FROM report_cells "
                        "WHERE level = :level GROUP BY status, category"
                    ),
                    {"level": TOTALS_LEVEL},
                )
            ).all()
            by_status: dict[str, int] = {}
            by_category: dict[str, int] = {}
            for status, category, n in rows:
                by_status[status] = by_status.get(status, 0) + n
                by_category[category] = by_category.get(category, 0) + n

            recent_rows = await db.execute(
                select(Report).order_by(Report.created_at.desc()).limit(5)
            )
            recent = [
                ReportResponse.model_validate(r).model_dump(mode="json")
                for r in recent_rows.scalars().all()
            ]

            return {
                "total_reports": sum(by_status.values()),
                "open_reports": by_status.get(ReportStatus.OPEN.value, 0),
                "in_progress_reports": by_status.get(ReportStatus.IN_PROGRESS.value, 0),
                "resolved_reports": by_status.get(ReportStatus.RESOLVED.value, 0),
                "by_category": by_category,
                "recent_reports": recent,
            }

        return await cached_json("cache:dashboard:v2", settings.DASHBOARD_CACHE_TTL_SECONDS, compute)

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
    ) -> str:
        """Grid-clustered reports for the viewport, read from the rollup.

        The viewport is snapped outward to the cluster grid so many users panning
        around the same area share one cache entry."""

        level = level_for_zoom(zoom)
        grid = grid_for_zoom(zoom)

        cx0, cx1 = cell_of(min_lat, grid), cell_of(max_lat, grid)
        cy0, cy1 = cell_of(min_lng, grid), cell_of(max_lng, grid)

        key = f"cache:clusters:v2:{level}:{cx0}:{cx1}:{cy0}:{cy1}:{status or '-'}:{category or '-'}"

        async def compute():
            sql = (
                "SELECT sum(sum_lat) / sum(cnt) AS latitude, sum(sum_lng) / sum(cnt) AS longitude, "
                "sum(cnt)::bigint AS count FROM report_cells "
                "WHERE level = :level AND cx BETWEEN :cx0 AND :cx1 AND cy BETWEEN :cy0 AND :cy1"
            )
            params: dict = {"level": level, "cx0": cx0, "cx1": cx1, "cy0": cy0, "cy1": cy1}
            if status:
                sql += " AND status = :status"
                params["status"] = status
            if category:
                sql += " AND category = :category"
                params["category"] = category
            sql += " GROUP BY cx, cy HAVING sum(cnt) > 0"

            rows = (await db.execute(text(sql), params)).all()
            return [
                {"latitude": float(r.latitude), "longitude": float(r.longitude), "count": int(r.count)}
                for r in rows
            ]

        return await cached_json(key, settings.CLUSTER_CACHE_TTL_SECONDS, compute)
