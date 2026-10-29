import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# Tests run against a real PostGIS database (see docs/TESTING in the tracker).
# DATABASE_URL must point at a throwaway database that has been migrated.
from app.core.redis import close_redis, get_redis  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE reports, outbox_events, officers, areas RESTART IDENTITY CASCADE"))
    redis = get_redis()
    if redis is not None:
        await redis.flushdb()  # throwaway test Redis only
    yield
    # Each test runs in its own event loop; drop pooled connections bound to it.
    await engine.dispose()
    await close_redis()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def sample_report(**overrides):
    data = {
        "title": "Large pothole",
        "description": "Large pothole near the market",
        "category": "Road",
        "latitude": 28.6139,
        "longitude": 77.2090,
        "address": "Connaught Place",
        "landmark": "Metro gate 3",
        "city": "Delhi",
        "district": "New Delhi",
        "state": "Delhi",
        "pincode": "110001",
    }
    data.update(overrides)
    return data
