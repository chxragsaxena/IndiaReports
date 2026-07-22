from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report
from app.models.enums import ReportStatus
from app.schemas.report import ReportCreate


class ReportService:

    @staticmethod
    async def create_report(
        db: AsyncSession,
        report: ReportCreate,
    ) -> Report:

        db_report = Report(
            **report.model_dump()
        )

        db.add(db_report)

        await db.commit()

        await db.refresh(db_report)

        return db_report

    @staticmethod
    async def get_reports(
        db: AsyncSession,
    ):

        result = await db.execute(
            select(Report)
        )

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