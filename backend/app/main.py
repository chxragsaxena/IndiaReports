import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.redis import close_redis, get_redis
from app.db.session import engine
from app.events.outbox import run_relay


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    relay_task = asyncio.create_task(run_relay(stop))
    try:
        yield
    finally:
        stop.set()
        await relay_task
        await close_redis()
        await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    # Wildcard origins cannot be combined with credentials; this API uses no cookies.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    api_router,
    prefix="/api/v1",
)


@app.get("/health")
async def health():
    """Liveness: the process is up."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """Readiness: database reachable. Redis is optional and reported, not required."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    redis_state = "disabled"
    client = get_redis()
    if client is not None:
        try:
            await client.ping()
            redis_state = "up"
        except Exception:
            redis_state = "down"

    return {"status": "ready", "database": "up", "redis": redis_state}
