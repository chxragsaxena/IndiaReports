# IndiaReports

Report civic issues on a map of India, watch them appear live, and see which ones get fixed. Reports are routed to the officer responsible
for that area and escalate to an administrator if nobody acknowledges them.

```
React + MapLibre (Vercel)
   |
   +--> report-service  (Python/FastAPI, PostGIS)   reports, map clusters/pins, areas, officers, escalation
   +--> notifier        (Go)                        live WebSocket pins, Telegram alerts
   +--> analytics       (Go)                        trends, hotspots, resolution leaderboard
              ^ events over Redis Streams, each service owns its own database
```

More: [architecture](docs/ARCHITECTURE.md), [load test and capacity](docs/LOADTEST.md), [project tracker](docs/TRACKER.md).

## Run everything locally
```
docker compose up --build
docker compose run --rm --entrypoint python report-service -m scripts.seed_areas     # demo officers + areas
docker compose run --rm --entrypoint python report-service -m scripts.seed_reports   # 500 reports with 30 days of history
cd frontend && npm ci && npm run dev
```
Service ports: report-service 8000, notifier 8100, analytics 8200 (change with `REPORT_PORT`, `NOTIFIER_PORT`, `ANALYTICS_PORT`, `POSTGRES_PORT`, `REDIS_PORT`).
Seeding twice does not reset analytics; use `docker compose down -v` for a clean slate.

## Tests
| What | Command |
|---|---|
| report-service | with the compose Postgres/Redis up and a throwaway database: `pytest` (see `docs/TRACKER.md` for the exact container command) |
| notifier / analytics | `go test -race ./...` in each service folder |
| across services | `go test -tags integration ./integration/` in `services/notifier` (run on a **fresh** stack: `docker compose down -v` first) |
| frontend | `npm run build` (strict TypeScript) |
| load | see `docs/LOADTEST.md` |

## Configuration
- **report-service**: `DATABASE_URL`, `REDIS_URL` (optional), `ADMIN_API_KEY`, `JWT_SECRET`, `REQUIRE_LOGIN_TO_REPORT`, `ACK_SECRET`, `CORS_ORIGINS`, `ESCALATION_AFTER_SECONDS` (default 7 days),
  `WEB_CONCURRENCY`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `RATE_LIMIT_PER_MINUTE`.
- **notifier**: `DATABASE_URL`, `REDIS_URL`, `TELEGRAM_BOT_TOKEN` (alerts are logged only when unset), `APP_URL`, `CORS_ORIGINS`.
- **analytics**: `DATABASE_URL`, `REDIS_URL`, `CORS_ORIGINS`.
- **frontend (Vercel)**: `VITE_API_URL`, `VITE_NOTIFIER_URL`, `VITE_ANALYTICS_URL` (the last two optional), `VITE_MAP_STYLE`, `VITE_TELEGRAM_BOT`.

## Deploying (Render + Vercel)
- Run `alembic upgrade head` on the report-service database. If that database predates these migrations and was not created by alembic,
  run `alembic stamp e1e34496a6ba` first.
- One Render web service per backend service, plus a Render Key Value (Redis) instance. Free tiers sleep, so the first request after idle is slow.
- Set `ADMIN_API_KEY` (and ideally a separate `ACK_SECRET`) to long random values.
- `frontend/vercel.json` rewrites client routes so deep links such as `/ack?...` work.

## Accounts
Citizens sign up on the site. Create the first administrator from the command line (it prompts for the password, or set `ADMIN_PASSWORD`):
```
docker compose run --rm --entrypoint python report-service -m scripts.create_admin you@yourdomain.org "Your Name"
```
Then sign in on the **Administrator** tab. Set `JWT_SECRET` to a long random value and `REQUIRE_LOGIN_TO_REPORT=true` in production.
