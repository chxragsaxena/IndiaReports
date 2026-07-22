from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.dashboard import DashboardResponse
from app.db.session import get_db
from app.schemas.report import ReportCreate, ReportResponse
from app.services.report_service import ReportService

router = APIRouter()


@router.post(
    "/",
    response_model=ReportResponse,
    status_code=201,
)
async def create_report(
    report: ReportCreate,
    db: AsyncSession = Depends(get_db),
):
    return await ReportService.create_report(
        db=db,
        report=report,
    )


@router.get(
    "/",
    response_model=list[ReportResponse],
)
async def get_reports(
    db: AsyncSession = Depends(get_db),
):
    return await ReportService.get_reports(db)

@router.get(
    "/dashboard",
    response_model=DashboardResponse,
)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
):
    return await ReportService.get_dashboard(db)