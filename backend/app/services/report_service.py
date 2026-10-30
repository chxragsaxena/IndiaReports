import math
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cached_json
from app.core.config import settings
from app.core.security import Staff
from app.models.area import Officer
from app.models.user import User
from app.services.email_service import assigned_notice, queue_email, reopened_notice, resolved_notice
from app.events.outbox import (
    add_event,
    report_created_payload,
    status_changed_payload,
)
from app.models.enums import ReportStatus
from app.models.report import Report, ReportSupporter
from app.services.similarity import find_similar
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
        reporter_id: uuid.UUID | None = None,
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
            reporter_id=reporter_id,
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

        # Does an open report about the same problem already exist right here? Staff are told;
        # the citizen was already offered "me too" before submitting, and nothing is hidden.
        category = getattr(report.category, "value", report.category)
        similar = await find_similar(db, report.latitude, report.longitude, category, report.title, report.description, limit=1)
        if similar:
            db_report.possible_duplicate_of = similar[0].report.id

        db.add(db_report)

        # The event is written in the SAME transaction as the report. The map/dashboard
        # rollup is updated from it by a background applier (app/events/rollup.py), not
        # here: updating shared cell rows in every request would make all writes in one
        # area queue on the same locks.
        add_event(db, "ReportCreated", report_created_payload(db_report, recipient))
        # The text goes to the ai-service on its own event: ReportCreated is broadcast to the live
        # map, which has no business carrying the description.
        add_event(db, "ReportTriageRequested", {
            "report_id": str(db_report.id), "title": db_report.title,
            "description": db_report.description, "category": db_report.category,
        })

        # Tell the responsible officer by email too, if they have an account.
        if assignee is not None and assignee.user_id is not None:
            officer_user = await db.get(User, assignee.user_id)
            if officer_user is not None:
                subject, body = assigned_notice(db_report, assignee.name)
                await queue_email(db, officer_user.email, subject, body, f"assigned:{db_report.id}")

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
        staff: Staff | None = None,
        note: str | None = None,
    ) -> Report | None:
        """Change a report's status as staff. Returns None when the report does not exist or
        is not in this officer's queue (the same answer for both, so ids cannot be probed)."""
        result = await db.execute(
            select(Report).where(Report.id == report_id).with_for_update()
        )
        report = result.scalar_one_or_none()
        if report is None or (staff is not None and not staff.can_see(report)):
            return None

        if report.archived_at is not None:
            raise HTTPException(status_code=409, detail="This report has been closed and archived.")

        old_status = report.status
        if old_status == new_status.value:
            return report  # idempotent: no change, no event

        report.status = new_status.value
        changed_at = datetime.now(timezone.utc)
        if report.acknowledged_at is None and new_status != ReportStatus.OPEN:
            report.acknowledged_at = changed_at  # someone acted on it

        if new_status == ReportStatus.RESOLVED:
            report.resolved_at = changed_at
            report.resolved_by = staff.user.id if staff and staff.user else None
            report.resolution_note = (note or "").strip() or None
            report.confirmed_at = None
            await ReportService._tell_reporter_resolved(db, report)
        elif old_status == ReportStatus.RESOLVED.value:
            # Staff reopened it themselves: back in the queue with a fresh deadline.
            report.resolved_at = report.resolved_by = report.resolution_note = report.confirmed_at = None
            report.assigned_at = changed_at

        add_event(db, "ReportStatusChanged", status_changed_payload(report, old_status, changed_at))

        await db.commit()
        await db.refresh(report)
        return report

    @staticmethod
    async def _tell_reporter_resolved(db: AsyncSession, report: Report) -> None:
        stamp = int(report.resolved_at.timestamp()) if report.resolved_at else 0
        if report.reporter_id is not None:  # an anonymous report has nobody to write to
            reporter = await db.get(User, report.reporter_id)
            if reporter is not None:
                subject, body = resolved_notice(report, reporter.name)
                await queue_email(db, reporter.email, subject, body, f"resolved:{report.id}:{stamp}")
        # Everyone who said "me too" was waiting for this fix as well.
        supporters = (
            await db.execute(
                select(User).join(ReportSupporter, ReportSupporter.user_id == User.id).where(ReportSupporter.report_id == report.id)
            )
        ).scalars().all()
        for person in supporters:
            subject, body = resolved_notice(report, person.name)
            await queue_email(db, person.email, subject, body, f"resolved:{report.id}:{stamp}:{person.id}")

    @staticmethod
    async def support(db: AsyncSession, report_id: uuid.UUID, user: User) -> tuple[Report, bool]:
        """"Me too": add this person to the people affected. Counted once per person, and the
        reporter is already counted. Returns the report and whether this call added someone."""
        if user.role in ("admin", "officer"):
            raise HTTPException(status_code=403, detail="Staff cannot add themselves as affected residents.")
        report = (await db.execute(select(Report).where(Report.id == report_id).with_for_update())).scalar_one_or_none()
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found.")
        if report.status == ReportStatus.RESOLVED.value or report.archived_at is not None:
            raise HTTPException(status_code=409, detail="This problem has already been fixed.")
        if report.reporter_id == user.id:
            return report, False
        added = (
            await db.execute(
                pg_insert(ReportSupporter)
                .values(report_id=report.id, user_id=user.id)
                .on_conflict_do_nothing()
                .returning(ReportSupporter.user_id)
            )
        ).first()
        if added is not None:
            report.affected_count = report.affected_count + 1
        await db.commit()
        await db.refresh(report)
        return report, added is not None

    @staticmethod
    async def _own_resolved_report(db: AsyncSession, report_id: uuid.UUID, user: User) -> Report:
        """The reporter's own resolved report that is still within its checking window, locked."""
        report = (
            await db.execute(select(Report).where(Report.id == report_id).with_for_update())
        ).scalar_one_or_none()
        # Same answer for "does not exist" and "not yours".
        if report is None or report.reporter_id != user.id:
            raise HTTPException(status_code=404, detail="Report not found.")
        if report.status != ReportStatus.RESOLVED.value or report.archived_at is not None:
            raise HTTPException(status_code=409, detail="This report is no longer open for checking.")
        return report

    @staticmethod
    async def confirm_resolved(db: AsyncSession, report_id: uuid.UUID, user: User) -> Report:
        """The reporter checked and the fix is real. The report then leaves the map early."""
        report = await ReportService._own_resolved_report(db, report_id, user)
        if report.confirmed_at is None:
            report.confirmed_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(report)
        return report

    @staticmethod
    async def reopen(db: AsyncSession, report_id: uuid.UUID, user: User, reason: str | None) -> Report:
        """The reporter checked and it is not fixed. It goes back to the officer with a new deadline."""
        report = await ReportService._own_resolved_report(db, report_id, user)
        now = datetime.now(timezone.utc)

        report.status = ReportStatus.OPEN.value
        report.resolved_at = report.resolved_by = report.resolution_note = report.confirmed_at = None
        report.acknowledged_at = None
        report.assigned_at = now  # the clock starts again
        add_event(db, "ReportStatusChanged", status_changed_payload(report, ReportStatus.RESOLVED.value, now))

        officer = await db.get(Officer, report.assigned_officer_id) if report.assigned_officer_id else None
        if officer is not None and officer.user_id is not None:
            officer_user = await db.get(User, officer.user_id)
            if officer_user is not None:
                subject, body = reopened_notice(report, officer.name, (reason or "").strip() or None)
                await queue_email(db, officer_user.email, subject, body, f"reopened:{report.id}:{int(now.timestamp())}")

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

        query = select(Report).where(Report.archived_at.is_(None))

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
            ).where(_viewport_filter(min_lat, max_lat, min_lng, max_lng), Report.archived_at.is_(None))
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
                select(Report).where(Report.archived_at.is_(None)).order_by(Report.created_at.desc()).limit(5)
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
