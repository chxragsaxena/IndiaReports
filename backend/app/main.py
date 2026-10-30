import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as SATimeoutError
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.redis import close_redis, get_redis
from app.core.storage import get_store
from app.db.session import engine
from app.events.escalation import run_escalation
from app.core.auth import signing_source
from app.events.lifecycle import run_lifecycle
from app.events.mailer import run_mailer
from app.events.outbox import run_relay
from app.events.rollup import run_rollup


logger = logging.getLogger(__name__)

async def ensure_photo_bucket() -> None:
    """Create the photo bucket once object storage is reachable. Storage may start after this
    service, so keep trying for a while instead of failing startup."""
    store = get_store()
    if store is None:
        return
    for attempt in range(30):
        try:
            await store.ensure_ready()
            return
        except Exception:
            if attempt == 29:
                logger.warning("photo storage is configured but never became reachable", exc_info=True)
                return
            await asyncio.sleep(2)



@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()

    if signing_source() == "derived":
        logger.warning(
            "JWT_SECRET is not set: sign-in tokens are signed with a key derived from DATABASE_URL. "
            "It works, but set JWT_SECRET to a long random string."
        )

    tasks = [
        asyncio.create_task(ensure_photo_bucket()),
        asyncio.create_task(run_relay(stop)),
        asyncio.create_task(run_escalation(stop)),
        asyncio.create_task(run_rollup(stop)),
        asyncio.create_task(run_lifecycle(stop)),
        asyncio.create_task(run_mailer(stop)),
    ]
    try:
        yield
    finally:
        stop.set()
        await asyncio.gather(*tasks)
        await close_redis()
        await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    lifespan=lifespan,
)

# JSON for map views is large and very compressible; compress anything over 1 KB.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=4)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    # Wildcard origins cannot be combined with credentials; this API uses no cookies.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(SATimeoutError)
async def pool_exhausted(_: Request, __: SATimeoutError):
    """Every database connection is busy and the wait timed out: shed load politely.
    Clients (and load balancers) can retry shortly; this beats a slow 500 for everyone."""
    return JSONResponse(
        status_code=503,
        content={"detail": "The server is busy. Please try again in a moment."},
        headers={"Retry-After": "2"},
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

    return {"status": "ready", "database": "up", "redis": redis_state, "sign_in_key": signing_source()}
