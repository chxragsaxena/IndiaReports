import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.alerts import analysis_enabled
from app.core.auth import hash_password
from app.core.config import settings
from app.core.storage import get_store
from app.models.image import ReportImage
from app.schemas.image import AdminImage, AdminReportDetail
from app.core.security import Staff, require_admin, require_staff
from app.db.session import get_db
from app.models.area import Area, Officer
from app.models.report import Report
from app.models.user import User
from app.schemas.auth import AdminUserCreate, UserResponse
from app.schemas.admin import (
    AdminReportPage,
    AdminReportRow,
    AreaCreate,
    AreaResponse,
    OfficerAccount,
    OfficerCreate,
    OfficerResponse,
    QueueMap,
    QueueMapArea,
    QueueMapReport,
    StaffProfile,
)

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# Everything here needs staff. Managing areas, officers and accounts additionally needs the
# main administrator; an area officer only ever sees the reports assigned to them.
router = APIRouter(dependencies=[Depends(require_staff)])
main_only = [Depends(require_admin)]


def _foreign_language(triage: dict | None) -> str | None:
    language = (triage or {}).get("language")
    return language if language and language.lower() != "english" else None


def _due_at(report: Report) -> datetime | None:
    """When the responsible officer must resolve it by. None once resolved or escalated."""
    if report.status == "RESOLVED" or report.escalated_at is not None or report.assigned_at is None:
        return None
    return report.assigned_at + timedelta(seconds=settings.ESCALATION_AFTER_SECONDS)


@router.get("/me", response_model=StaffProfile)
async def staff_profile(staff: Staff = Depends(require_staff), db: AsyncSession = Depends(get_db)):
    area_name = None
    if staff.officer is not None and staff.officer.area_id is not None:
        area = await db.get(Area, staff.officer.area_id)
        area_name = area.name if area else None
    return StaffProfile(
        is_main=staff.is_main,
        name=(staff.officer.name if staff.officer else staff.user.name if staff.user else None),
        area_id=staff.officer.area_id if staff.officer else None,
        area_name=area_name,
        resolve_within_seconds=settings.ESCALATION_AFTER_SECONDS,
        resolved_visible_seconds=settings.RESOLVED_VISIBLE_SECONDS,
    )


@router.post("/areas", response_model=AreaResponse, status_code=201, dependencies=main_only)
async def create_area(body: AreaCreate, db: AsyncSession = Depends(get_db)):
    if body.geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise HTTPException(422, "geometry must be a GeoJSON Polygon or MultiPolygon.")

    geom = func.ST_Multi(
        func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(body.geometry)), 4326)
    )
    try:
        valid = (await db.execute(select(func.ST_IsValid(geom)))).scalar_one()
    except Exception:
        await db.rollback()
        raise HTTPException(422, "geometry is not valid GeoJSON.")
    if not valid:
        raise HTTPException(422, "polygon is invalid (for example self-intersecting).")

    area = Area(name=body.name, geom=geom)
    db.add(area)
    await db.commit()
    await db.refresh(area)
    return area


@router.get("/areas", response_model=list[AreaResponse], dependencies=main_only)
async def list_areas(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Area).order_by(Area.name).limit(1000))
    return result.scalars().all()


@router.post("/officers", response_model=OfficerResponse, status_code=201, dependencies=main_only)
async def create_officer(body: OfficerCreate, db: AsyncSession = Depends(get_db)):
    area = None
    if body.role == "officer":
        if body.area_id is None:
            raise HTTPException(422, "an officer must be assigned to an area.")
        area = await db.get(Area, body.area_id)
        if area is None:
            raise HTTPException(404, "area not found.")
    elif body.area_id is not None:
        raise HTTPException(422, "the admin is not tied to an area.")

    user = await _account_for(db, body.email, body.password, body.role, body.name)

    officer = Officer(
        name=body.name,
        role=body.role,
        telegram_chat_id=body.telegram_chat_id,
        area_id=body.area_id,
        user_id=user.id if user else None,
    )
    db.add(officer)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "an active main admin already exists, or that account is already an officer.")
    await db.refresh(officer)
    return _officer_response(officer, user.email if user else None, area.name if area else None)


async def _account_for(
    db: AsyncSession, email_in: str | None, password: str | None, officer_role: str, name: str
) -> User | None:
    """The sign-in account for an officer: an existing one is linked, otherwise one is
    created. Returns None when no email was given (a notification-only officer)."""
    if email_in is None:
        return None
    wanted_role = "officer" if officer_role == "officer" else "admin"
    email = email_in.lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is None:
        if not password:
            raise HTTPException(422, "a password is required to create a new account for this email.")
        user = User(email=email, name=name.strip(), password_hash=await hash_password(password), role=wanted_role)
        db.add(user)
        await db.flush()
        return user

    if user.role == "admin" and wanted_role == "officer":
        raise HTTPException(409, "that account is the main administrator; use a different email for an area officer.")
    user.role = wanted_role
    user.active = True
    return user


@router.put("/officers/{officer_id}/account", response_model=OfficerResponse, dependencies=main_only)
async def set_officer_account(officer_id: UUID, body: OfficerAccount, db: AsyncSession = Depends(get_db)):
    """Give an existing officer (for example one created before sign-in existed) an account to
    sign in with. Replacing it takes sign-in access away from the previous account."""
    officer = await db.get(Officer, officer_id)
    if officer is None:
        raise HTTPException(404, "officer not found.")

    user = await _account_for(db, body.email, body.password, officer.role, officer.name)
    if officer.user_id is not None and officer.user_id != user.id:
        previous = await db.get(User, officer.user_id)
        if previous is not None and previous.role in ("officer", "admin"):
            previous.role = "citizen"
    officer.user_id = user.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "that account is already linked to another officer.")
    area = await db.get(Area, officer.area_id) if officer.area_id else None
    return _officer_response(officer, user.email, area.name if area else None)


def _officer_response(officer: Officer, email: str | None, area_name: str | None) -> OfficerResponse:
    return OfficerResponse(
        id=officer.id, name=officer.name, role=officer.role, telegram_chat_id=officer.telegram_chat_id,
        area_id=officer.area_id, area_name=area_name, email=email, active=officer.active,
    )


@router.get("/officers", response_model=list[OfficerResponse], dependencies=main_only)
async def list_officers(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Officer, User.email, Area.name)
            .outerjoin(User, User.id == Officer.user_id)
            .outerjoin(Area, Area.id == Officer.area_id)
            .order_by(Officer.name)
            .limit(1000)
        )
    ).all()
    return [_officer_response(o, email, area_name) for o, email, area_name in rows]


@router.get("/reports", response_model=AdminReportPage)
async def list_reports_for_admin(
    status: str | None = None,
    needs_attention: bool = False,
    escalated: bool = False,
    overdue: bool = False,
    unresolved: bool = False,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    staff: Staff = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Reports with who they were sent to and whether anyone acted, newest first. An area
    officer gets only the reports assigned to them; the main administrator gets all of them.

    unresolved: everything still to be done. needs_attention: open and not yet acknowledged. escalated: moved to the main administrator
    because it was not resolved in time. overdue: past its deadline and about to escalate.
    Paged by `before` (keyset), so it stays fast on huge tables."""
    query = (
        select(Report, Officer.name, Officer.role)
        .outerjoin(Officer, Officer.id == Report.assigned_officer_id)
        .order_by(Report.created_at.desc())
        .limit(limit + 1)
    )
    if not staff.is_main:
        query = query.where(Report.assigned_officer_id == staff.officer.id)
    if status:
        query = query.where(Report.status == status)
    if unresolved:
        query = query.where(Report.status != "RESOLVED")
    if needs_attention:
        query = query.where(Report.status == "OPEN", Report.acknowledged_at.is_(None))
    if escalated:
        query = query.where(Report.escalated_at.is_not(None))
    if overdue:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.ESCALATION_AFTER_SECONDS)
        query = query.where(Report.status != "RESOLVED", Report.escalated_at.is_(None), Report.assigned_at <= cutoff)
    if before:
        query = query.where(Report.created_at < before)

    rows = (await db.execute(query)).all()
    page = rows[:limit]

    # One extra query for this page's photos (at most a few dozen rows), not one per report.
    photos: dict = {}
    if page:
        for report_id, severity, status_ in (
            await db.execute(
                select(ReportImage.report_id, ReportImage.severity, ReportImage.status).where(
                    ReportImage.report_id.in_([r.id for r, _, _ in page]), ReportImage.kind == "report"
                )
            )
        ).all():
            photos.setdefault(report_id, []).append((severity, status_))

    def summarise(report_id):
        images = photos.get(report_id, [])
        worst = max((s for s, _ in images if s), key=lambda s: SEVERITY_RANK.get(s, 0), default=None)
        return len(images), worst, any(st in ("pending", "analyzing") for _, st in images)

    now = datetime.now(timezone.utc)
    items = []
    for r, name, role in page:
        count, worst, pending = summarise(r.id)
        due = _due_at(r)
        items.append(
            AdminReportRow(
                id=r.id, title=r.title, category=r.category, status=r.status, city=r.city, state=r.state,
                latitude=r.latitude, longitude=r.longitude,
                created_at=r.created_at, assigned_at=r.assigned_at, acknowledged_at=r.acknowledged_at,
                escalated_at=r.escalated_at, resolved_at=r.resolved_at, archived_at=r.archived_at,
                resolution_note=r.resolution_note, due_at=due, overdue=bool(due and due <= now),
                assignee_name=name, assignee_role=role,
                image_count=count, ai_severity=worst, ai_pending=pending,
                affected_count=r.affected_count, ai_urgency=(r.triage or {}).get("urgency"), ai_spam=bool((r.triage or {}).get("is_spam")),
                language=_foreign_language(r.triage),
            )
        )
    next_before = page[-1][0].created_at if len(rows) > limit and page else None
    return AdminReportPage(items=items, next_before=next_before)


@router.post("/users", response_model=UserResponse, status_code=201, dependencies=main_only)
async def create_user(body: AdminUserCreate, db: AsyncSession = Depends(get_db)):
    """Administrators are only ever created here or by `python -m scripts.create_admin`."""
    email = body.email.lower()
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, name=body.name.strip(), password_hash=await hash_password(body.password), role=body.role)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "An account with this email already exists.")
    await db.refresh(user)
    return UserResponse(id=user.id, name=user.name, email=user.email, role=user.role)


@router.get("/reports/{report_id}", response_model=AdminReportDetail)
async def report_detail(
    report_id: UUID, staff: Staff = Depends(require_staff), db: AsyncSession = Depends(get_db)
):
    """One report with its photos and the AI findings about them. Photo links are short-lived."""
    report = await db.get(Report, report_id)
    # Same answer for "does not exist" and "not in your queue".
    if report is None or not staff.can_see(report):
        raise HTTPException(404, "Report not found.")

    images = (
        await db.execute(select(ReportImage).where(ReportImage.report_id == report_id).order_by(ReportImage.created_at))
    ).scalars().all()
    store = get_store()
    assignee = await db.get(Officer, report.assigned_officer_id) if report.assigned_officer_id else None

    original = await db.get(Report, report.possible_duplicate_of) if report.possible_duplicate_of else None
    possible_duplicate = {"id": str(original.id), "title": original.title, "status": original.status} if original else None

    return AdminReportDetail(
        id=report.id, title=report.title, description=report.description, category=report.category,
        status=report.status, address=report.address, city=report.city, district=report.district,
        state=report.state, pincode=report.pincode, latitude=report.latitude, longitude=report.longitude,
        created_at=report.created_at, assigned_at=report.assigned_at, due_at=_due_at(report),
        acknowledged_at=report.acknowledged_at, escalated_at=report.escalated_at,
        resolved_at=report.resolved_at, resolution_note=report.resolution_note,
        assignee_name=assignee.name if assignee else None,
        analysis_enabled=analysis_enabled(), triage=report.triage, affected_count=report.affected_count,
        possible_duplicate=possible_duplicate,
        images=[
            AdminImage(
                id=i.id,
                url=await store.presign_get(i.storage_key, settings.IMAGE_URL_TTL_SECONDS) if store else "",
                width=i.width, height=i.height, status=i.status, severity=i.severity, findings=i.analysis,
                kind=i.kind, verification=i.verification,
                provider=i.analysis_provider, model=i.analysis_model, error=i.error, analyzed_at=i.analyzed_at,
            )
            for i in images
        ],
    )


QUEUE_MAP_LIMIT = 1000


@router.get("/queue-map", response_model=QueueMap)
async def queue_map(staff: Staff = Depends(require_staff), db: AsyncSession = Depends(get_db)):
    """The staff member's queue on a map. An area officer gets their own area's boundary and the
    reports assigned to them; the main administrator gets every area and the newest reports.
    Archived reports (already off the public map) are left out."""
    area_query = select(Area.name, func.ST_AsGeoJSON(Area.geom)).order_by(Area.name).limit(1000)
    if not staff.is_main:
        area_query = area_query.where(Area.id == staff.officer.area_id)
    areas = [QueueMapArea(name=name, geometry=json.loads(geojson)) for name, geojson in (await db.execute(area_query)).all()]

    query = (
        select(Report)
        .where(Report.archived_at.is_(None))
        .order_by(Report.created_at.desc())
        .limit(QUEUE_MAP_LIMIT + 1)
    )
    if not staff.is_main:
        query = query.where(Report.assigned_officer_id == staff.officer.id)
    reports = (await db.execute(query)).scalars().all()

    now = datetime.now(timezone.utc)
    pins = []
    for r in reports[:QUEUE_MAP_LIMIT]:
        due = _due_at(r)
        pins.append(
            QueueMapReport(
                id=r.id, title=r.title, category=r.category, status=r.status, latitude=r.latitude,
                longitude=r.longitude, overdue=bool(due and due <= now), escalated=r.escalated_at is not None,
            )
        )
    return QueueMap(areas=areas, reports=pins, truncated=len(reports) > QUEUE_MAP_LIMIT)
