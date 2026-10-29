# IndiaReports - Microservices Conversion Tracker

Branch: `microservices` (never commit to `main` directly - it is live on Vercel/Render).
Legend: [x] done, [~] in progress, [ ] todo

## Decisions
- Small demo microservices, not a large system: **report-service** (Python/FastAPI), **notifier** (Go), **analytics** (Go).
- No API gateway. Frontend calls each service directly (CORS configured per service).
- Broker: **Redis Streams** (Render offers a free Redis-compatible Key Value store).
- Each service owns its own database. Local compose uses one Postgres instance with 3 databases.
- `backend/` and `frontend/` stay at their current paths so Render/Vercel root-directory settings keep working.
- Every service must degrade gracefully: if Redis is down/unset, report-service still works.
- Scale target: India scale. See `docs/ARCHITECTURE.md` for the scaling design and its honest limits.

## Stages
| # | Stage | Status |
|---|-------|--------|
| 1 | Scaffolding: tracker, architecture doc, compose, Dockerfile | [x] |
| 2 | report-service: status PATCH, SQL dashboard, indexes, outbox + event publishing, caching, rate limit | [x] |
| 3 | notifier (Go): stream consumer, WebSocket hub (geo-tiled), subscriptions, Telegram | [ ] |
| 4 | analytics (Go): rollup consumer, hotspots + SLA endpoints | [ ] |
| 5 | Frontend redesign: design system, map UI, dashboard, live pins, subscribe, XSS fix | [ ] |
| 6 | End-to-end verification, load test, README, deploy notes | [ ] |

## Log
- Stage 1 started: cloned repo to working folder, created `microservices` branch.

## Open items for the owner (cannot be done by the assistant)
- Create Render services (report-service, notifier, analytics) + Render Key Value (Redis); set env vars.
- Update Vercel env vars (`VITE_API_URL`, `VITE_NOTIFIER_URL`, `VITE_ANALYTICS_URL`) after services are live.
- Provide `TELEGRAM_BOT_TOKEN` if Telegram alerts are wanted.
- Set a real `ADMIN_API_KEY` in production.
- Stage 2 done (report-service). 11 tests pass against real PostGIS + Redis (9 pass / 2 skip with Redis unset).
  - Added: `PATCH /reports/{id}/status` (X-API-Key), `GET /reports/{id}`, `/ready`, outbox table + relay (SKIP LOCKED, multi-instance safe),
    Redis cache for dashboard + clusters (viewport snapped to grid), per-IP write rate limit, row cap on list endpoint,
    indexes (status+category, created_at, state+city), SQL `GROUP BY` dashboard (was loading every row), `by_category` in dashboard.
  - Fixed: dashboard "recent reports" was arbitrary order; `backend/alembic/env.py` was missing from the repo (migrations could not run);
    `DEBUG` defaulted to True (SQL echo in prod); CORS wildcard combined with credentials.
  - Input validation added: coordinates must be inside India's bounding box; length limits on text fields.

## Running the tests
```
POSTGRES_PORT=5433 REDIS_PORT=6380 docker compose up -d postgres redis
docker compose build report-service
docker compose run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/reports_db \
  -e ADMIN_API_KEY=testkey --entrypoint sh report-service \
  -c "pip install -q -r requirements-dev.txt && alembic upgrade head && pytest -q"
```
(Tests TRUNCATE tables and FLUSHDB Redis - use only a throwaway stack.)

## Owner notes for report-service deploy
- New optional env vars: `REDIS_URL`, `ADMIN_API_KEY`, `CORS_ORIGINS` (set to your Vercel URL), `RATE_LIMIT_PER_MINUTE`.
- Without `REDIS_URL` everything works as before; events accumulate in `outbox_events` and are published once Redis is configured.
- Run `alembic upgrade head` on the Render database. If that database was NOT created by alembic, stamp it first
  (`alembic stamp e1e34496a6ba`) so the first two migrations are not re-run.
