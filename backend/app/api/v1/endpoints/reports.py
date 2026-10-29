from typing import Optional
from uuid import UUID

import uuid as uuid_module

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user_optional, require_user
from app.core.images import ImageRejected, TooLarge, process_image, read_limited
from app.core.storage import get_store
from app.models.image import ReportImage
from app.models.report import Report
from app.schemas.image import ImageUploadResponse
from app.core.config import settings
from app.core.rate_limit import rate_limit_uploads, rate_limit_writes
from app.models.user import User
from app.core.security import Staff, require_staff
from app.db.session import get_db
from app.schemas.admin import AcknowledgeRequest
from app.schemas.report import ReopenRequest, ReportCreate, ReportResponse, ReportStatusUpdate
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
)
async def update_report_status(
    report_id: UUID,
    body: ReportStatusUpdate,
    staff: Staff = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Staff change a report's status. An area officer can only act on reports assigned to
    them. Resolving records who did it and the note, and emails the person who reported it."""
    report = await ReportService.update_status(db, report_id, body.status, staff=staff, note=body.note)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@router.post("/{report_id}/confirm", response_model=ReportResponse)
async def confirm_report_resolved(
    report_id: UUID,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """The person who reported it says the fix is real; it then leaves the public map."""
    return await ReportService.confirm_resolved(db, report_id, user)


@router.post("/{report_id}/reopen", response_model=ReportResponse, dependencies=[Depends(rate_limit_writes)])
async def reopen_report(
    report_id: UUID,
    body: ReopenRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """The person who reported it says it is not fixed: back to the officer, deadline restarted."""
    return await ReportService.reopen(db, report_id, user, body.reason)


@router.post(
    "/{report_id}/images",
    response_model=ImageUploadResponse,
    status_code=201,
    dependencies=[Depends(rate_limit_uploads)],
)
async def upload_report_image(
    report_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach a photo to a report. Only the person who filed it (or an admin) may add photos.
    The file is checked and re-encoded, so only a clean, bounded JPEG is ever stored."""
    store = get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Photo uploads are not available right now.")

    report = await db.get(Report, report_id)
    # Same answer for "does not exist" and "not yours", so ids cannot be probed.
    if report is None or (report.reporter_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="Report not found.")

    try:
        raw = await read_limited(file, settings.MAX_UPLOAD_BYTES)
        processed = await process_image(raw)
    except TooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except ImageRejected as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Serialise uploads for this report so the per-report limit cannot be raced past.
    await db.execute(select(Report.id).where(Report.id == report_id).with_for_update())
    existing = (
        await db.execute(select(func.count()).select_from(ReportImage).where(ReportImage.report_id == report_id))
    ).scalar_one()
    if existing >= settings.MAX_IMAGES_PER_REPORT:
        raise HTTPException(status_code=409, detail=f"A report can have at most {settings.MAX_IMAGES_PER_REPORT} photos.")

    image_id = uuid_module.uuid4()
    key = f"reports/{report_id}/{image_id}.jpg"
    await store.put(key, processed.data, processed.content_type)
    db.add(
        ReportImage(
            id=image_id,
            report_id=report_id,
            uploader_id=user.id,
            storage_key=key,
            content_type=processed.content_type,
            size_bytes=len(processed.data),
            width=processed.width,
            height=processed.height,
        )
    )
    await db.commit()
    return ImageUploadResponse(id=image_id, width=processed.width, height=processed.height)
