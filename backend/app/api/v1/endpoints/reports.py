from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user_optional
from app.core.config import settings
from app.core.rate_limit import rate_limit_writes
from app.models.user import User
from app.core.security import require_admin
from app.db.session import get_db
from app.schemas.admin import AcknowledgeRequest
from app.schemas.report import ReportCreate, ReportResponse, ReportStatusUpdate
from app.services import assignment_service
from app.services.report_service import ReportService

router = APIRouter()

# Read endpoints serve ready-made JSON text from the cache. A few seconds of public
# caching lets browsers and a CDN absorb repeated identical requests as well.
READ_CACHE_CONTROL = "public, max-age=5"


def json_response(body: str) -> Response:
    return Response(content=body, media_type="application/json", headers={"Cache-Control": READ_CACHE_CONTROL})


@router.post(
    "/",
    response_model=ReportResponse,
    status_code=201,
    dependencies=[Depends(rate_limit_writes)],
)
async def create_report(
    report: ReportCreate,
    db: AsyncSession = Depends(get_db),
    reporter: User | None = Depends(current_user_optional),
):
    if reporter is None and settings.REQUIRE_LOGIN_TO_REPORT:
        raise HTTPException(status_code=401, detail="Please sign in to report an issue.")
    return await ReportService.create_report(
        db=db,
        report=report,
        reporter_id=reporter.id if reporter else None,
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

    status: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
):
    return await ReportService.get_reports(
        db=db,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lng=min_lng,
        max_lng=max_lng,
        status=status,
        category=category,
        limit=limit,
    )


@router.get("/dashboard")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
):
    """Totals, per-category counts and the 5 latest reports (JSON, see DashboardResponse)."""
    return json_response(await ReportService.get_dashboard(db))


@router.get("/clusters")
async def get_clusters(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    zoom: int,
    status: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Clusters for a viewport: a list of {latitude, longitude, count}."""
    return json_response(
        await ReportService.get_clusters(
            db=db,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lng=min_lng,
            max_lng=max_lng,
            zoom=zoom,
            status=status,
            category=category,
        )
    )


@router.get("/pins")
async def get_pins(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    status: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Map pins for a viewport: {truncated, pins: [{id, status,
    latitude, longitude}]}. Fetch the full record by id when a pin is opened."""
    return json_response(
        await ReportService.get_pins(
            db=db,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lng=min_lng,
            max_lng=max_lng,
            status=status,
            category=category,
        )
    )


@router.get(
    "/{report_id}",
    response_model=ReportResponse,
)
async def get_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    report = await ReportService.get_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@router.post(
    "/{report_id}/acknowledge",
    response_model=ReportResponse,
)
async def acknowledge_report(
    report_id: UUID,
    body: AcknowledgeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Called from the signed link in the officer's alert. No login: the token proves
    the caller received the alert for this report."""
    try:
        return await assignment_service.acknowledge(db, report_id, body.token)
    except assignment_service.AckError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.patch(
    "/{report_id}/status",
    response_model=ReportResponse,
    dependencies=[Depends(require_admin)],
)
async def update_report_status(
    report_id: UUID,
    body: ReportStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    report = await ReportService.update_status(db, report_id, body.status)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report
