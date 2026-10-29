import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.core.security import require_admin
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
    OfficerCreate,
    OfficerResponse,
)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.post("/areas", response_model=AreaResponse, status_code=201)
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


@router.get("/areas", response_model=list[AreaResponse])
async def list_areas(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Area).order_by(Area.name).limit(1000))
    return result.scalars().all()


@router.post("/officers", response_model=OfficerResponse, status_code=201)
async def create_officer(body: OfficerCreate, db: AsyncSession = Depends(get_db)):
    if body.role == "officer":
        if body.area_id is None:
            raise HTTPException(422, "an officer must be assigned to an area.")
        if await db.get(Area, body.area_id) is None:
            raise HTTPException(404, "area not found.")
    elif body.area_id is not None:
        raise HTTPException(422, "the admin is not tied to an area.")

    officer = Officer(
        name=body.name,
        role=body.role,
        telegram_chat_id=body.telegram_chat_id,
        area_id=body.area_id,
    )
    db.add(officer)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "an active main admin already exists.")
    await db.refresh(officer)
    return officer


@router.get("/officers", response_model=list[OfficerResponse])
async def list_officers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Officer).order_by(Officer.name).limit(1000))
    return result.scalars().all()


@router.get("/reports", response_model=AdminReportPage)
async def list_reports_for_admin(
    status: str | None = None,
    needs_attention: bool = False,
    escalated: bool = False,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Reports with who they were sent to and whether anyone acted, newest first.

    needs_attention: open and not yet acknowledged. escalated: moved to the admin because
    nobody acknowledged in time. Paged by `before` (keyset), so it stays fast on huge tables."""
    query = (
        select(Report, Officer.name, Officer.role)
        .outerjoin(Officer, Officer.id == Report.assigned_officer_id)
        .order_by(Report.created_at.desc())
        .limit(limit + 1)
    )
    if status:
        query = query.where(Report.status == status)
    if needs_attention:
        query = query.where(Report.status == "OPEN", Report.acknowledged_at.is_(None))
    if escalated:
        query = query.where(Report.escalated_at.is_not(None))
    if before:
        query = query.where(Report.created_at < before)

    rows = (await db.execute(query)).all()
    page = rows[:limit]
    items = [
        AdminReportRow(
            id=r.id, title=r.title, category=r.category, status=r.status, city=r.city, state=r.state, latitude=r.latitude, longitude=r.longitude,
            created_at=r.created_at, assigned_at=r.assigned_at, acknowledged_at=r.acknowledged_at,
            escalated_at=r.escalated_at, assignee_name=name, assignee_role=role,
        )
        for r, name, role in page
    ]
    next_before = page[-1][0].created_at if len(rows) > limit and page else None
    return AdminReportPage(items=items, next_before=next_before)


@router.post("/users", response_model=UserResponse, status_code=201)
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
