from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    burn_password_check,
    create_token,
    hash_password,
    require_user,
    verify_password,
)
from app.core.config import settings
from app.core.rate_limit import rate_limit_auth
from app.db.session import get_db
from app.models.report import Report
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.schemas.report import ReportResponse

router = APIRouter()
me_router = APIRouter()


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_token(user),
        expires_in=settings.JWT_TTL_SECONDS,
        user=UserResponse(id=user.id, name=user.name, email=user.email, role=user.role),
    )


@router.post("/register", response_model=TokenResponse, status_code=201, dependencies=[Depends(rate_limit_auth)])
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a citizen account. This can never create an administrator."""
    email = body.email.lower()
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(
        email=email,
        name=body.name.strip(),
        password_hash=await hash_password(body.password),
        role="citizen",
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:  # two sign-ups for the same email raced
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    await db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit_auth)])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None:
        await burn_password_check(body.password)
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if not user.active or not await verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return _token_response(user)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(require_user)):
    return UserResponse(id=user.id, name=user.name, email=user.email, role=user.role)


@me_router.get("/reports", response_model=list[ReportResponse])
async def my_reports(
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """The signed-in person's own reports, newest first."""
    query = select(Report).where(Report.reporter_id == user.id).order_by(Report.created_at.desc()).limit(limit)
    if before:
        query = query.where(Report.created_at < before)
    return (await db.execute(query)).scalars().all()
