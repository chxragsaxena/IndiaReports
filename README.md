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

## Photos and AI analysis
Citizens can attach up to 3 photos to a report. Photos are private: only the reporter and administrators can see them, through short-lived signed links.
An open-source vision model looks at each photo and reports findings to the administrator (what it shows, severity, hazards, whether the category fits,
a suggested action). Serious findings (high or critical severity, or inappropriate content) also message the admin on Telegram.

**Run the model yourself.** The service talks to any server that speaks the OpenAI chat API with image input (Ollama, vLLM, llama.cpp, LM Studio),
so photos never leave your infrastructure and there is no per-image fee. Configure it with `ANALYSIS_BASE_URL` and `ANALYSIS_MODEL`.

| Where | What to run | Notes |
|---|---|---|
| A laptop (CPU only, about 8 GB RAM) | Ollama with a small Qwen3-VL (for example `qwen3-vl:2b` or `qwen3-vl:4b`) | Works for demos but is slow (a minute or more per photo). Give Docker at least 6 GB if you use the bundled `ollama` container. |
| Production | vLLM on a GPU server with a larger Qwen3-VL (for example the 32B) | Much better quality. Only `ANALYSIS_BASE_URL` and `ANALYSIS_MODEL` change. |

Local example with the bundled container (needs several GB of RAM and a multi-GB download):
```
docker compose --profile ai up -d ollama
docker compose exec ollama ollama pull qwen3-vl:2b
# in .env:   ANALYSIS_BASE_URL=http://ollama:11434/v1   ANALYSIS_MODEL=qwen3-vl:2b
docker compose up -d report-service
```
Check the model name against the Ollama library or the model card; `ollama pull` fails clearly if a tag does not exist.
Without a model, `ANALYSIS_PROVIDER=mock` shows the whole flow with clearly labelled demo findings (and never messages anyone); leave it empty to turn analysis off.

**Photo storage** is any S3-compatible service: the compose file runs an open-source one for local use; in production set `S3_ENDPOINT_URL`, `S3_BUCKET`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY` (and `S3_PUBLIC_URL` if browsers reach it at a different address) for S3 or Cloudflare R2. Leave `S3_ENDPOINT_URL` unset to turn uploads off.

**Treat findings as assistive.** Small open models are far weaker than frontier ones, and nobody has measured this model's accuracy on Indian civic photos.
Before letting severity drive alerts in production, collect a set of real photos with known answers and check the model against it.
