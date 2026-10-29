"""Make an account an administrator, creating it or resetting its password if asked.

    python -m scripts.make_admin you@example.com                 promote an account that already exists
    python -m scripts.make_admin you@example.com 'NewPassword'   create it, or reset its password, and promote it

Meant for the Start Command on hosts with no shell (Render free tier). It needs no API key.
Without a password it does nothing, and exits successfully, if the email has not signed up yet,
so it never blocks a deploy. Running it again is harmless. A password given on the command line
is visible in the host's settings: remove it from the Start Command once it has worked.
"""

import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import hash_password
from app.core.config import settings
from app.models.user import User

logger = logging.getLogger("make_admin")

MIN_PASSWORD = 8


async def promote(email: str, password: str | None = None, name: str | None = None) -> bool:
    """True if the account is now an administrator. With no password, False means there is no such
    account yet. With a password the account is created (or its password reset) and promoted."""
    email = email.strip().lower()
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: AsyncSession
            user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if user is None:
                if not password:
                    return False
                user = User(email=email, name=name or email.split("@")[0], password_hash=await hash_password(password), role="admin")
                db.add(user)
            else:
                user.role, user.active = "admin", True
                if password:
                    user.password_hash = await hash_password(password)
            await db.commit()
            return True
    finally:
        await engine.dispose()


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(argv) not in (2, 3) or "@" not in argv[1]:
        logger.error("usage: python -m scripts.make_admin you@example.com [new-password]")
        sys.exit(2)
    password = argv[2] if len(argv) == 3 else None
    if password is not None and len(password) < MIN_PASSWORD:
        logger.error("the password must be at least %d characters", MIN_PASSWORD)
        sys.exit(2)
    if asyncio.run(promote(argv[1], password)):
        logger.info("%s is an administrator%s", argv[1], " (password set)" if password else "")
    else:
        logger.info("no account for %s yet: sign up first, or give a password to create it, then restart", argv[1])


if __name__ == "__main__":
    main(sys.argv)
