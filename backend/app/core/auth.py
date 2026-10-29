"""Passwords, sign-in tokens, and the dependencies that turn a request into a user."""

import asyncio
import hashlib
import hmac
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


def signing_source() -> str:
    """Where the sign-in signing key comes from: 'env' (JWT_SECRET or ADMIN_API_KEY) or 'derived'."""
    return "env" if (settings.JWT_SECRET or settings.ADMIN_API_KEY) else "derived"


def _secret() -> str:
    """Key that signs sign-in tokens. Prefer an explicit secret. Without one, derive a key from
    the database connection string (its password is unique to this deployment, never public, and
    stable across restarts and instances) so sign-in still works instead of failing. Setting
    JWT_SECRET is better: it can be rotated without changing the database password."""
    explicit = settings.JWT_SECRET or settings.ADMIN_API_KEY
    if explicit:
        return explicit
    return hmac.new(settings.DATABASE_URL.encode(), b"indiareports/sign-in/v1", hashlib.sha256).hexdigest()


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
