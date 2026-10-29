# IndiaReports Architecture

```
React (Vite, Vercel)
   |  REST                         |  WebSocket (live pins)      |  REST (stats)
   v                               v                             v
report-service (FastAPI)       notifier (Go)                 analytics (Go)
   |  reports_db                  |  notifier_db                |  analytics_db
   |  PostGIS                     |  subscriptions, deliveries  |  rollups
   |                              ^                             ^
   +--> outbox --> Redis Streams "reports.events" ---------------+
                   (consumer groups: notifier, analytics)
```

## Services
| Service | Lang | Owns | Responsibility |
|---|---|---|---|
| report-service | Python/FastAPI | reports_db | Create/query reports, clusters, status changes, publishes events |
| notifier | Go | notifier_db | Live WebSocket fan-out, area subscriptions, Telegram alerts |
| analytics | Go | analytics_db | Hotspots, time-to-resolve, per-state/category rollups |

No service reads another service's database. They only share events on the stream.

## Events (Redis Stream `reports.events`)
- `ReportCreated`: id, title, category, status, lat, lng, city, state, pincode, created_at
- `ReportStatusChanged`: id, old_status, new_status, category, state, city, created_at, changed_at

Delivery is at-least-once, so every consumer must be idempotent (keyed by event id).

## Scaling design (India scale)
Be clear about what is designed in versus what has been verified. The design below is built to scale horizontally, but it has **not** been run across multiple machines or at 100M users, and nobody can honestly claim that from a laptop. What was measured on one machine, what failed first and what was fixed is in `docs/LOADTEST.md`.

1. **Stateless services.** No in-process state that matters (the in-process cache is only a fallback). Run N copies behind a load balancer.
2. **Read path is cheap.** Clusters and dashboard numbers are read from a precomputed grid rollup (`report_cells`), not computed from the reports table. Responses are cached as finished JSON in Redis with single-flight (one request recomputes an expired key, the rest wait), and the cache key snaps the viewport to a grid so many users share entries. See `docs/LOADTEST.md`.
3. **Bounded responses.** Report list queries have a hard row cap; clusters aggregate in the database. No endpoint returns an unbounded result set.
4. **Write path is decoupled.** A report insert plus its outbox row are one DB transaction. A relay publishes to the stream, so a Redis outage never loses an event and never blocks report creation.
5. **Fan-out by geography.** WebSocket clients join geo-tile rooms for their viewport; a new report is sent only to clients in that tile, not to everyone. Every notifier instance reads the whole event stream itself, so any instance can serve any client and no cross-instance messaging is needed.
6. **Rollups, not scans.** Analytics updates counters per event (upserts into rollup tables). Dashboards never scan the raw reports table.
7. **Abuse protection.** Per-IP rate limiting on writes via Redis; admin-only status changes behind an API key.
8. **Database path to scale.** Connection pooling (use PgBouncer in front of Postgres), read replicas for the read-heavy endpoints, and partitioning `reports` by time (or state) once row counts reach hundreds of millions.

## Failure behaviour
- Redis down: report-service keeps accepting and serving reports (events wait in the outbox).
- notifier or analytics down: nothing user-facing breaks except live pins/stats; they catch up from the stream when they return.

## Accountability: area officers and escalation
Every report is routed to a named person, and silence is not allowed to hide a problem.

1. **Areas** are PostGIS `MULTIPOLYGON`s (GiST-indexed); each **officer** belongs to one area. There is exactly one active **main admin**.
2. **Assignment** happens in the same transaction as the report insert: the officer of the *smallest* area that `ST_Contains` the point
   wins (a ward officer beats a district officer). If no area matches, the admin is assigned.
3. The `ReportCreated` event carries the recipient. The notifier messages that person directly with a **signed acknowledge link**
   (HMAC over report id + officer id, no login needed). Re-assigning a report invalidates the previous person's link.
4. **Acknowledging** (via the link, or an admin moving the status past OPEN) stamps `acknowledged_at` and moves OPEN to IN_PROGRESS.
5. **Escalation**: a background job in report-service finds reports that are OPEN, unacknowledged and older than
   `ESCALATION_AFTER_SECONDS` (default 7 days), reassigns them to the admin and emits `ReportEscalated`. It runs on every instance
   safely (`FOR UPDATE SKIP LOCKED`), escalates each report at most once, and a partial index keeps the lookup tiny at any table size.

Security: the recipient's chat id and token travel only on the internal stream. The notifier strips them from every WebSocket
payload (covered by a test) and redacts tokens from logs.

## Read and write paths (what the load test changed)
- **Writes never touch shared hot rows.** A request inserts the report and an outbox event in one transaction and returns. A background applier
  (`app/events/rollup.py`) folds events into the rollup in batches. The map and dashboard lag by about a second (eventual consistency).
- **Clusters** are a range scan over `report_cells` (levels for zoom 3-10, finer grids as you zoom in). Pins (zoom 11+) are `id, status, lat, lng` only; the
  full record is fetched by id when a pin is opened.
- **Connection budget.** workers x instances x (pool + overflow) must stay under the database `max_connections`; behind PgBouncer it can be much larger.
  When the pool is exhausted the API answers `503` with `Retry-After`, not a slow `500`.
- **Repair.** `python -m scripts.rebuild_cells` rebuilds the rollup from the reports table (run it after bulk loads that bypass the app).

## Sign-in and roles
- Two roles: **citizen** (self-service sign-up with email + password; can report and see their own reports) and **admin** (never self-service;
  created with `python -m scripts.create_admin` or `POST /api/v1/admin/users` by an existing admin).
- The sign-in page's Citizen/Administrator tabs only choose which form to show. The server decides the role, and re-checks it on every request:
  the role and the `active` flag are read from the database (not trusted from the token), so demoting or disabling an admin takes effect at once.
- Passwords are hashed with argon2id (off the event loop). Sign-in gives clear reasons (no account for this email / incorrect password / account disabled). This does reveal which emails have accounts, as sign-up already does, so scanning is limited by the per-IP rate limit below (a deliberate trade for clarity),
  and register/login are rate limited per IP (needs Redis; without it only the slow hash limits guessing).
- Tokens are short-lived JWTs (default 8 h) sent as `Authorization: Bearer`, kept in `sessionStorage` (tab-scoped). No cookies, so no CSRF surface;
  the trade-off is that an XSS bug could read the token, which is why user text is never injected as HTML.
- The service API key (`X-API-Key`) still works for scripts and tests, but a signed-in non-admin is refused even if they also send it.
- `REQUIRE_LOGIN_TO_REPORT=true` refuses anonymous reports (off by default for compatibility; turn it on in production). Reports record `reporter_id` when signed in.

Not built: email verification, password reset, "remember me", multi-factor sign-in, token revocation lists (disable the user instead), audit log of admin actions.
