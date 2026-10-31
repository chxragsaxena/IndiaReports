"""One-time email links (password reset, address verification)."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_token import AuthToken
from app.models.user import User

RESET_TTL = timedelta(hours=1)
VERIFY_TTL = timedelta(days=2)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


async def issue(db: AsyncSession, user: User, kind: str, ttl: timedelta) -> tuple[str, uuid.UUID]:
    """A fresh link for this person. Older unused links of the same kind stop working, so only the
    newest email in their inbox is valid. The secret is returned once and never stored."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user.id, AuthToken.kind == kind, AuthToken.used_at.is_(None))
        .values(used_at=now)
    )
    secret = secrets.token_urlsafe(32)
    row = AuthToken(id=uuid.uuid4(), user_id=user.id, kind=kind, token_hash=_digest(secret), expires_at=now + ttl)
    db.add(row)
    await db.flush()
    return secret, row.id


async def consume(db: AsyncSession, secret: str, kind: str) -> User | None:
    """Spend a link and return its owner, or None if it is unknown, expired or already used.
    The row is locked, so two clicks at once cannot both succeed."""
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.token_hash == _digest(secret), AuthToken.kind == kind, AuthToken.used_at.is_(None), AuthToken.expires_at > now)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.used_at = now
    return await db.get(User, row.user_id)
