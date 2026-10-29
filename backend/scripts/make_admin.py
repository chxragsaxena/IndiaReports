"""Make an existing account an administrator.

    python -m scripts.make_admin you@example.com

Meant for the Start Command on hosts with no shell (Render free tier), after the person has
signed up through the site. It needs no API key. It does nothing, and exits successfully, if
the email has not signed up yet, so it never blocks a deploy. Running it again is harmless.
"""

import asyncio
import logging
import sys

from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models.user import User

logger = logging.getLogger("make_admin")


async def promote(email: str) -> bool:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                update(User).where(User.email == email.strip().lower()).values(role="admin", active=True)
            )
            return result.rowcount > 0
    finally:
        await engine.dispose()


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(argv) != 2 or "@" not in argv[1]:
        logger.error("usage: python -m scripts.make_admin you@example.com")
        sys.exit(2)
    if asyncio.run(promote(argv[1])):
        logger.info("%s is an administrator", argv[1])
    else:
        logger.info("no account for %s yet: sign up first, then restart the service", argv[1])


if __name__ == "__main__":
    main(sys.argv)
