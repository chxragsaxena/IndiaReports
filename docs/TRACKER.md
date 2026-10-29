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
| 3 | notifier (Go): stream consumer, WebSocket hub (geo-tiled), subscriptions, Telegram | [x] |
| 4 | analytics (Go): rollup consumer, hotspots + SLA endpoints | [x] |
| 4b | Area polygons + officer assignment (PostGIS ST_Contains), acknowledge link, 7-day escalation to admin, notifier direct messages | [x] |
| 5 | Frontend redesign: design system, map UI, dashboard, live pins, subscribe, acknowledge page, XSS fix | [x] |
| 6 | End-to-end verification, load test, README, deploy notes | [x] |

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
- Stage 3 done (notifier). Unit tests pass with `-race`; integration test passes against the live compose stack.
  - Verified end to end: report -> outbox -> Redis stream -> notifier. Mumbai viewer got the pin live, India-wide viewer got a throttled
    `refresh`, Delhi viewer got nothing, matching subscriber delivered exactly once, out-of-area subscriber not notified.
  - Design: live reader (every instance sees every event, feeds its own WebSocket clients) + consumer group (each event alerted once
    across instances, XAUTOCLAIM recovery, dead-letter stream). Geo-tile fan-out (1 degree tiles), slow clients dropped, connection cap.
  - Protocol docs: `services/notifier/README.md`.
  - Known limit: Telegram can only message users who started the bot. No per-user auth on subscriptions (chat_id is the identity).
- Stage 4 done (analytics). Verified against the live stack: summary, trends, leaderboard and hotspots return correct numbers for
  generated events; repeat requests hit the in-process cache. Rollup updates are idempotent (processed_events in the same transaction).
- New requirement from owner (2026-10-29): notify the officer responsible for the polygon/area a report falls in; if not acknowledged
  within 7 days, escalate to the main admin. Tracked as stage 4b below. The core backend stays Python/FastAPI (report-service owns PostGIS).
- Stage 4b done (area officers + escalation). Backend: 22 tests pass (20 + 2 Redis-only skipped when Redis unset). Go: unit tests pass with `-race`.
  Live-stack integration: report in a ward polygon -> officer alerted -> no acknowledgement -> (5 s test window) admin alerted with a new token.
  - Added: `areas`/`officers` tables, `/api/v1/admin/areas|officers` (X-API-Key), `POST /reports/{id}/acknowledge` (signed token),
    escalation loop, `ReportEscalated` event, notifier direct messages, `scripts/seed_areas.py` (10 city jurisdictions + admin).
  - Security checks: public WebSocket payload never contains recipient chat id / token (unit + integration test); tokens redacted in logs.
  - Owner action: set `ACK_SECRET` (or `ADMIN_API_KEY`) in production; set `ADMIN_CHAT_ID`/`OFFICER_CHAT_ID` before running seed_areas to receive real alerts.
  - Frontend TODO (stage 5): `/ack?report=&token=` page that POSTs to the acknowledge endpoint.
  - Known limit: escalation is one level (officer -> admin) and happens once; the admin is not escalated further.
- Stage 5 done (frontend redesign). Verified in a real headless browser against the live compose stack (screenshots of map, drawer,
  insights, report form incl. validation errors, acknowledge page, mobile layouts); a report created via the API arrived in the open page
  over WebSocket and no private fields were present in the frames. `npm run build` and `tsc --strict` are clean.
  - New: design tokens + component library (Button/Badge/Card/fields/Toast/Modal/Skeleton), map-centric Home (filter panel, live indicator,
    clickable stats, details drawer with accountability timeline), report form (inline validation, use-my-location, address autofill),
    Insights (KPIs, trend chart, categories, hotspots, state leaderboard), acknowledge page, alerts dialog, 404 page.
  - Security/robustness: popups that injected unescaped user text into HTML are gone (XSS); `alert()` replaced by toasts; stale map requests
    are aborted; WebSocket drops when the tab is hidden and reconnects with jittered backoff; pages are code-split (map library only loads
    on map pages); `frontend/vercel.json` rewrites client-side routes so `/ack?...` deep links from alerts do not 404.
  - Map tiles: OpenFreeMap (free, no key) instead of the MapLibre demo tiles. Override with `VITE_MAP_STYLE`.
  - Address autofill uses OpenStreetMap Nominatim (best effort, light use only). Swap for a self-hosted/paid geocoder at scale.
  - Seed: `scripts.seed_reports` was broken against the current schema (no `geom`); rewritten with 30 days of history, officer assignment,
    historical events (analytics counts them, notifier ignores them). NOTE: re-seeding does not reset analytics; use `docker compose down -v`.
  - Compose fix: Postgres healthcheck now checks TCP (the socket check passed during first-boot init and services crashed).
  - Google Maps: not used (cost + would require replacing the map). Optional later: Places Autocomplete on the report form behind `VITE_GOOGLE_MAPS_KEY`.

## Frontend env vars (set in Vercel)
`VITE_API_URL` (report-service), `VITE_NOTIFIER_URL`, `VITE_ANALYTICS_URL` (both optional: features hide/degrade when unset),
`VITE_MAP_STYLE` (optional), `VITE_TELEGRAM_BOT` (optional, bot username for the alerts dialog), `VITE_ESCALATION_DAYS` (default 7).
- Stage 6 done (verification, load test, docs). The first load test FAILED (22 req/s, p95 24 s, 11% errors at 200 users) and drove real fixes:
  grid rollup for clusters/dashboard (cold cluster query 0.72 s -> 0.036 s, independent of table size), single-flight JSON cache, lightweight
  pins endpoint + gzip, rollup applied by a background worker instead of inside the write transaction (writes 36 -> 152-210 req/s), bounded
  DB/Redis connection pools with 503 + Retry-After when saturated (a `too many clients` crash was found and fixed).
  Final numbers, rig limits and what is NOT proven are in `docs/LOADTEST.md`. 5,000 concurrent WebSocket viewers: 100% delivery, p95 0.9 s, ~180 MB.
  - Tests: backend 33 pass (31 + 2 Redis-only skipped when Redis unset); Go unit tests pass with `-race`; cross-service integration tests pass on a fresh stack.
  - Test lessons: two tests passed vacuously at first (invalid titles were rejected with 422 and the responses were ignored); fixed and guarded.
    Backend tests TRUNCATE tables: always point them at a throwaway database (`reports_test`), never the dev database.
  - New files: `docs/LOADTEST.md`, root `README.md`, `loadtest/`, `services/notifier/loadtest/ws/`.
  - Map semantics changed: clusters up to zoom 10, pins from zoom 11 (was 8). Pins endpoint reports `truncated` if a view has more than 500.

- Auth added (2026-10-29): citizen/admin sign-in, role-based pages, admin report dashboard with live updates, "My reports". 47 backend tests pass; the whole
  flow was driven in a real browser (15 checks). A real bug was found and fixed on the way: the live-update hook could drop its viewport in dev (React double-mount race).
  Demo admin for local use only: admin@example.org / ChangeMe-Admin-123 (change or delete it; never deploy it).

- Photos + AI analysis added (2026-10-29): upload with re-encoding, private storage, open-source vision model via an OpenAI-compatible server, admin drawer with findings.
  83 backend tests, Go suites, and a real-browser run (compression, signed link, findings) pass. Verified with the fake model server and the labelled demo analyzer;
  NOT yet run against a real local model (no Ollama installed, laptop has 7.7 GB RAM and no GPU). Two infrastructure surprises: MinIO no longer publishes free images
  (switched to Zenko CloudServer), and that server needs its host names configured (`ENDPOINT`).

- Photo analysis re-based on the PullWise pattern (2026-10-29): Groq (hosted open-weight models, GROQ_API_KEY) or a self-run Ollama/vLLM server over the OpenAI-compatible API,
  strict JSON schema, finish_reason checks, 429 handling (Retry-After, 30 s cap, 2 retries, injectable sleep). 94 backend tests pass. NOT yet run against live Groq (needs the key).
  Default Groq model is meta-llama/llama-4-scout-17b-16e-instruct (vision-capable per Groq docs seen via secondary sources); PullWise gpt-oss-120b is text-only.
  Privacy note recorded: with Groq, photos leave our infrastructure.
  VERIFIED LIVE (2026-10-29): the first default (Llama 4 Scout) no longer exists on Groq; the key lists gpt-oss (text-only), Whisper, TTS and qwen/qwen3.8-27b. The Qwen model accepts images
  and returns schema-valid findings in about a second: garbage photo under the wrong category was caught, hostile text in a report did not change the rating (one trial, not a guarantee),
  a real pothole road photo rated High at 95% and produced the admin alert. Default is now qwen/qwen3.8-27b. Accuracy still unmeasured on a real labelled set.

- Merged to `main` and deployed (2026-10-29). Render builds from `main` with root directory `backend`, so only changes under `backend/` trigger a deploy
  (docs, frontend and Go changes do not). Render runs Python 3.14, so every pinned package needs a 3.14 wheel:
  orjson and Pillow had none and the build failed compiling Rust; Pillow was bumped and orjson was dropped (cached responses use the standard `json`). Commits 72a14b1, f94327d.
  Render had also built a stale commit until a manual redeploy; check the commit shown on the service matches `main`.
- Map resilience (ff5fee3): the live frontend was talking to an older backend with no `/pins` route and a free-tier server that sleeps ~50 s. The map now falls back to the
  list endpoint on 404, waits up to 60 s, retries, and shows loading/error banners instead of a blank map.
- Live state after the deploy: new code is running but the Render database had NOT been migrated, so `/reports/dashboard` and `/reports/clusters` returned 500 (no `report_cells` table).
  Fix: `backend/scripts/migrate.py`, run from the Start Command before uvicorn. It handles a new database, a tracked one, and an old database never recorded by alembic
  (stamps it at e1e34496a6ba first), and is safe to run on every start. Tested against all three states and run twice.
  Render Start Command: `python -m scripts.migrate && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## Still open (owner decisions / not done)
- Render env vars still to set: `JWT_SECRET` (long random string; without it the admin key signs tokens), `CORS_ORIGINS` (the Vercel URL), then create the first admin
  (`POST /api/v1/admin/users` with `X-API-Key`). Photos/AI on Render need `S3_*` storage settings and `GROQ_API_KEY`; Redis is not configured there (caching falls back to per-process).
- The Go notifier and analytics services are not deployed on Render; the live site uses report-service only (live updates and Insights-from-analytics need those two).
- Google address search on the report form was discussed, not built (terms of use for Places/Geocoding with a non-Google map must be checked first).
- Not built: multi-machine test, PgBouncer in compose, Telegram fan-out beyond one bot, admin UI for areas/officers (API only).
