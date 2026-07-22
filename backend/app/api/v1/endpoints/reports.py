from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.cluster import ClusterResponse
from app.services.report_service import ReportService
from app.schemas.dashboard import DashboardResponse
from app.schemas.report import ReportCreate, ReportResponse

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

    min_lat: Optional[float] = Query(default=None),
    max_lat: Optional[float] = Query(default=None),

    min_lng: Optional[float] = Query(default=None),
    max_lng: Optional[float] = Query(default=None),
):
    return await ReportService.get_reports(
        db=db,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lng=min_lng,
        max_lng=max_lng,
    )


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
):
    return await ReportService.get_dashboard(db)


@router.get(
    "/clusters",
    response_model=list[ClusterResponse],
)
async def get_clusters(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    zoom: int,
    db: AsyncSession = Depends(get_db),
):
    
    return await ReportService.get_clusters(
        db=db,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lng=min_lng,
        max_lng=max_lng,
        zoom=zoom,
    )