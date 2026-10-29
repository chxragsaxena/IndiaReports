"""Bring the database up to date. Safe to run on every start.

    python -m scripts.migrate

Handles the three situations a deployment can be in:
  * a new empty database                       -> run every migration
  * a database already tracked by alembic      -> run only the new migrations
  * an older database that has the tables but was never recorded by alembic
    (it was built before migrations were tracked) -> record it at the last
    migration it already had, then run the new ones

so one start command works for the first deploy and for every deploy after it.
"""

import asyncio
import logging
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

logger = logging.getLogger("migrate")

# The last migration that existed before migrations were tracked in production.
BASELINE_REVISION = "e1e34496a6ba"


async def _state() -> tuple[bool, bool]:
    """(alembic knows this database, the reports table already exists)"""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            tracked = (await conn.execute(text("SELECT to_regclass('public.alembic_version')"))).scalar() is not None
            has_reports = (await conn.execute(text("SELECT to_regclass('public.reports')"))).scalar() is not None
            return tracked, has_reports
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = Config("alembic.ini")

    tracked, has_reports = asyncio.run(_state())
    if not tracked and has_reports:
        logger.info("existing database without migration history: recording it at %s", BASELINE_REVISION)
        command.stamp(config, BASELINE_REVISION)
    elif not tracked:
        logger.info("new database: running every migration")
    else:
        logger.info("database is tracked: running new migrations")

    command.upgrade(config, "head")
    logger.info("database is up to date")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("migration failed")
        sys.exit(1)
