"""Permanently delete an account: its sign-in, whether citizen, officer or administrator.

    python -m scripts.delete_user you@example.com

Meant for the Start Command on hosts with no shell (Render free tier), then removed again.
The person's reports are kept but no longer belong to anyone (they stay on the map and in
officers' queues). An officer record linked to the account stays, without a sign-in. Does
nothing, and exits successfully, if there is no such account.
"""

import asyncio
import logging
import sys

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models.user import User

logger = logging.getLogger("delete_user")


async def remove(email: str) -> bool:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(delete(User).where(User.email == email.strip().lower()))
            return result.rowcount > 0
    finally:
        await engine.dispose()


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(argv) != 2 or "@" not in argv[1]:
        logger.error("usage: python -m scripts.delete_user you@example.com")
        sys.exit(2)
    if asyncio.run(remove(argv[1])):
        logger.info("deleted the account for %s", argv[1])
    else:
        logger.info("no account for %s: nothing to delete", argv[1])


if __name__ == "__main__":
    main(sys.argv)
