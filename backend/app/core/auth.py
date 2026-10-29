"""Passwords, sign-in tokens, and the dependencies that turn a request into a user."""

import asyncio
import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

_hasher = PasswordHasher()  # argon2id with the library's recommended parameters
_dummy_hash: str | None = None


async def hash_password(password: str) -> str:
    # Hashing is deliberately slow and CPU-bound: keep it off the event loop.
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    def check() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(check)


async def burn_password_check(password: str) -> None:
    """Spend the same time as a real check when the email is unknown, so response
    time does not reveal which emails have accounts."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password("not-a-real-password")
    await verify_password(_dummy_hash, password)


def _secret() -> str:
    secret = settings.JWT_SECRET or settings.ADMIN_API_KEY
    if not secret:
        raise HTTPException(status_code=503, detail="Sign-in is not configured.")
    return secret


def create_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": str(user.id), "role": user.role, "iat": now, "exp": now + settings.JWT_TTL_SECONDS}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def _decode(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def current_user_optional(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """The signed-in user, or None for anonymous requests. A present but invalid or
    expired token is an error (401), not silently treated as anonymous."""
    token = bearer_token(authorization)
    if token is None:
        return None
    claims = _decode(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session.")
    # Role and active flag come from the database, not the token, so removing an
    # admin or deactivating an account takes effect immediately.
    user = await db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Invalid session.")
    return user


async def require_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user
