import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.analysis.analyzer import build_analyzer, resolve_provider
from app.config import settings
from app.reporting import ReportServiceClient
from app.store import build_store
from app.worker import run_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True) if settings.REDIS_URL else None
    analyzer, store = build_analyzer(), build_store()
    app.state.redis, app.state.analyzer = redis, analyzer

    if redis is None:
        logger.warning("REDIS_URL is not set: no events can be received, nothing will be analysed")
    elif analyzer is None:
        logger.info("photo analysis is off (no model configured): photos are stored, findings are not produced")
    elif store is None:
        logger.warning("S3_ENDPOINT_URL is not set: photos cannot be read, nothing will be analysed")
    elif not settings.INTERNAL_API_KEY:
        logger.warning("INTERNAL_API_KEY is not set: results would be refused, nothing will be analysed")
    else:
        tasks.append(asyncio.create_task(run_worker(stop, redis, analyzer, store, ReportServiceClient())))

    yield

    stop.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if redis is not None:
        await redis.aclose()


app = FastAPI(title="IndiaReports AI service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    redis_ok = False
    if app.state.redis is not None:
        try:
            redis_ok = bool(await app.state.redis.ping())
        except Exception:
            redis_ok = False
    analyzer = app.state.analyzer
    return {
        "redis": redis_ok,
        "photo_analysis": {"provider": analyzer.provider, "model": analyzer.model} if analyzer else resolve_provider(),
    }
