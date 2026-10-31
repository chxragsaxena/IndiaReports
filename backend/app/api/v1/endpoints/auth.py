from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_token,
    hash_password,
    require_user,
    verify_password,
)
from app.core.config import settings
from app.core.mailer import email_enabled
from app.core.rate_limit import rate_limit_auth
from app.core.tokens import RESET_TTL, VERIFY_TTL, consume, issue
from app.db.session import get_db
from app.models.report import Report
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenOnly,
    TokenResponse,
    UserResponse,
)
from app.services.email_service import queue_email, reset_notice, verify_notice
from app.schemas.report import ReportResponse

router = APIRouter()
me_router = APIRouter()


def _profile(user: User) -> UserResponse:
    return UserResponse(
        id=user.id, name=user.name, email=user.email, role=user.role, email_verified=user.email_verified_at is not None
    )


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_token(user), expires_in=settings.JWT_TTL_SECONDS, user=_profile(user))


async def send_verification(db: AsyncSession, user: User) -> None:
    """Queue the "confirm your email" link. Does nothing when email is not set up."""
    if not email_enabled():
        return
    secret, token_id = await issue(db, user, "verify", VERIFY_TTL)
    subject, body = verify_notice(user.name, secret)
    await queue_email(db, user.email, subject, body, f"verify:{token_id}")


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
        await db.flush()
        await send_verification(db, user)
        await db.commit()
    except IntegrityError:  # two sign-ups for the same email raced
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    await db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit_auth)])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    # Clear messages beat vague ones here: sign-up already reveals whether an email has
    # an account, so hiding it on sign-in protected little and confused real people.
    # Per-IP rate limiting (rate_limit_auth) is what limits scanning and guessing.
    if user is None:
        raise HTTPException(status_code=404, detail="No account is linked to this email. Create an account to continue.")
    if not user.active:
        raise HTTPException(status_code=403, detail="This account has been disabled. Contact an administrator.")
    if not await verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="Incorrect password. Please try again.")
    return _token_response(user)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(require_user)):
    return _profile(user)


@router.post("/forgot-password", dependencies=[Depends(rate_limit_auth)])
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Email a reset link. The answer is the same whether or not the address has an account, so this
    cannot be used to find out who is registered."""
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is not None and user.active and email_enabled():
        secret, token_id = await issue(db, user, "reset", RESET_TTL)
        subject, text = reset_notice(user.name, secret)
        await queue_email(db, user.email, subject, text, f"reset:{token_id}")
        await db.commit()
    return {"ok": True}


@router.post("/reset-password", dependencies=[Depends(rate_limit_auth)])
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Choose a new password with a link from the email. Every older sign-in stops working."""
    user = await consume(db, body.token, "reset")
    if user is None or not user.active:
        await db.rollback()
        raise HTTPException(status_code=400, detail="This link is invalid or has expired. Ask for a new one.")
    now = datetime.now(timezone.utc)
    user.password_hash = await hash_password(body.password)
    user.password_changed_at = now
    if user.email_verified_at is None:
        user.email_verified_at = now  # they just proved they can read this inbox
    await db.commit()
    return {"ok": True}


@router.post("/verify-email", dependencies=[Depends(rate_limit_auth)])
async def verify_email(body: TokenOnly, db: AsyncSession = Depends(get_db)):
    user = await consume(db, body.token, "verify")
    if user is None:
        await db.rollback()
        raise HTTPException(status_code=400, detail="This link is invalid or has expired. Ask for a new one.")
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.post("/resend-verification", dependencies=[Depends(rate_limit_auth)])
async def resend_verification(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    if user.email_verified_at is None:
        await send_verification(db, user)
        await db.commit()
    return {"ok": True}


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
