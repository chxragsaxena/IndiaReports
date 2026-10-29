import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.db.session import get_db
from app.models.area import Area, Officer
from app.schemas.admin import (
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
