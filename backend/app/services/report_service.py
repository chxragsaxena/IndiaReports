from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from app.models.report import Report
from app.models.enums import ReportStatus
from app.schemas.report import ReportCreate

from geoalchemy2.elements import WKTElement

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
            )
        )
        db.add(db_report)

        await db.commit()

        await db.refresh(db_report)

        return db_report

    @staticmethod
    async def get_reports(
        db: AsyncSession,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lng: float | None = None,
        max_lng: float | None = None,
        status: str | None = None,
        category: str | None = None,
    ):

        query = select(Report)

        if (
            min_lat is not None
            and max_lat is not None
            and min_lng is not None
            and max_lng is not None
        ):
            query = query.where(
                func.ST_Intersects(
                    Report.geom,
                    func.ST_MakeEnvelope(
                        min_lng,
                        min_lat,
                        max_lng,
                        max_lat,
                        4326,
                    ),
                )
            )

        if status:
            query = query.where(
                    Report.status == status
                )

        if category:
            query = query.where(
                    Report.category == category
                )

        result = await db.execute(query)

        return result.scalars().all()

    @staticmethod
    async def get_dashboard(
        db: AsyncSession,
    ):

        result = await db.execute(
            select(Report)
        )

        reports = result.scalars().all()

        return {
            "total_reports": len(reports),

            "open_reports": sum(
                report.status == ReportStatus.OPEN
                for report in reports
            ),

            "in_progress_reports": sum(
                report.status == ReportStatus.IN_PROGRESS
                for report in reports
            ),

            "resolved_reports": sum(
                report.status == ReportStatus.RESOLVED
                for report in reports
            ),

            "recent_reports": list(
                reversed(reports[-5:])
            ),
        }
    
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
        """
        Return clustered reports.
        """

        grid_size = 0.5 / (2 ** max(0, zoom - 4))

        query = (
    select(
        func.avg(Report.latitude).label("latitude"),
        func.avg(Report.longitude).label("longitude"),
        func.count().label("count"),
    )
    .where(
        func.ST_Intersects(
            Report.geom,
            func.ST_MakeEnvelope(
                min_lng,
                min_lat,
                max_lng,
                max_lat,
                4326,
            ),
        )
    )
)

        if status:
            query = query.where(
                Report.status == status
            )

        if category:
            query = query.where(
                Report.category == category
            )

        query = query.group_by(
            func.floor(Report.latitude / grid_size),
            func.floor(Report.longitude / grid_size),
        )

        result = await db.execute(query)

        return result.mappings().all()