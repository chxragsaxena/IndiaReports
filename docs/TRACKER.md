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
| 2 | report-service: status PATCH, SQL dashboard, indexes, outbox + event publishing, caching, rate limit | [ ] |
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
