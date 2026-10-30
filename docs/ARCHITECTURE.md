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
                   (consumer groups: notifier, analytics, ai-service)

ai-service (FastAPI) <-- ReportImageUploaded -- Redis Streams
   |  reads the photo from object storage (S3) and runs the vision model
   +--> POST /api/v1/internal/images/{id}/analysis  (X-Internal-Key)  --> report-service
```

## Services
| Service | Lang | Owns | Responsibility |
|---|---|---|---|
| report-service | Python/FastAPI | reports_db | Create/query reports, clusters, status changes, publishes events |
| notifier | Go | notifier_db | Live WebSocket fan-out, area subscriptions, Telegram alerts |
| analytics | Go | analytics_db | Hotspots, time-to-resolve, per-state/category rollups |
| ai-service | Python/FastAPI | nothing (its queue is the Redis stream) | Reads uploaded photos, runs open-weight models, posts findings back to report-service |

No service reads another service's database. They share events on the stream, and the ai-service sends its results back over a key-protected HTTP endpoint.

### The ai-service
A photo upload stages a `ReportImageUploaded` event in the same transaction as the photo row. The ai-service is a consumer group on the stream: a message stays pending until it is acknowledged, so a crash or a model outage loses nothing, and a failed attempt is redelivered after 1 min, 5 min, then 30 min (3 attempts). It is stateless (no database), keeps a per-day cap in Redis, and posts findings to the report-service, which stores them and decides who is alerted. The endpoint is idempotent, so a redelivered result alerts nobody twice. If the ai-service is down, reports and uploads keep working; photos wait for findings.

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
4. **Acknowledging** (via the link, or staff moving the status past OPEN) stamps `acknowledged_at` and moves OPEN to IN_PROGRESS.
   It does not stop the deadline clock.
5. **Escalation**: the officer must **resolve** the report within `ESCALATION_AFTER_SECONDS` (default 7 days) of it being assigned.
   A background job in report-service finds reports that are not RESOLVED and past that, reassigns them to the main admin, emits
   `ReportEscalated` and emails the admin. It runs on every instance safely (`FOR UPDATE SKIP LOCKED`), escalates each report at most once,
   and a partial index keeps the lookup tiny at any table size.

Security: the recipient's chat id and token travel only on the internal stream. The notifier strips them from every WebSocket
payload (covered by a test) and redacts tokens from logs.

### Decentralised administration (area officers)
Administration is split by area instead of sitting with one person. An **officer** record can be tied to a sign-in account
(`officers.user_id`, user role `officer`). Signed in, an officer sees only the reports assigned to them (`Staff.can_see`): another
area's report answers 404, the same as one that does not exist. The **main admin** sees everything and alone manages areas, officers
and accounts (the Team page). Officers get an email for each new report in their area, and for a reopen.

### Resolution lifecycle (what the citizen sees)
1. An officer marks a report **RESOLVED** with a note (`resolution_note`, public, written for the citizen). `resolved_at` and
   `resolved_by` are recorded and the reporter is emailed (queued in the same transaction, see below).
2. The report **stays on the public map** for `RESOLVED_VISIBLE_SECONDS` (default 3 days). During that window the reporter, and only
   the reporter, can **confirm** the fix or **reopen** it. Reopening returns it to the officer as OPEN with a fresh 7-day deadline.
3. After the window (or immediately once confirmed) a lifecycle job **archives** it (`archived_at`) and emits `ReportArchived`. The rollup
   applier subtracts it from the map counts, and pins, lists and the dashboard exclude archived rows. Nothing is deleted: it stays in the
   reporter's "My reports" and in the officers' lists. Rebuilding the rollup from scratch also leaves archived rows out.
4. Anyone can still open an archived report by its id. A resolved report that has been archived can no longer be reopened (file a new one).

### Email
Emails are rows in `email_jobs`, inserted in the same transaction as the change that causes them, with a `dedupe_key` so a retried request
cannot queue the same notice twice. A background worker (`SKIP LOCKED`, safe on many instances) sends them and retries failures with
growing delays (1 min doubling to 6 h, 6 attempts), so a provider outage delays email but never loses it. Delivery is at-least-once.
Providers: Resend (HTTPS API; use this on Render's free tier, which blocks SMTP), SMTP, or `log` for development. With none configured
nothing is queued and the app works as before. User-written text is stripped of control characters before it reaches a header.

### Escalating to higher agencies (designed, deliberately not built)
Today there is one escalation step: officer, then main admin. The real structure has more levels (ward, city, district, state), and the
same mechanism extends to them without new machinery:
- add `areas.parent_id` so areas form a tree, and `areas.resolve_within_seconds` so each level has its own deadline;
- give each level's officer an escalation target (their area's parent officer instead of "the" admin);
- make the escalation job climb one level per missed deadline, emitting `ReportEscalated` each time, and keep a `report_escalations`
  history table so the whole chain is visible on the report.
`escalated_at` would become the latest escalation and the timeline would list every step. Nothing else (assignment, queue scoping, emails,
the map lifecycle) needs to change, because they all key off `assigned_officer_id`.

## Read and write paths (what the load test changed)
- **Writes never touch shared hot rows.** A request inserts the report and an outbox event in one transaction and returns. A background applier
  (`app/events/rollup.py`) folds events into the rollup in batches. The map and dashboard lag by about a second (eventual consistency).
- **Clusters** are a range scan over `report_cells` (levels for zoom 3-10, finer grids as you zoom in). Pins (zoom 11+) are `id, status, lat, lng` only; the
  full record is fetched by id when a pin is opened.
- **Connection budget.** workers x instances x (pool + overflow) must stay under the database `max_connections`; behind PgBouncer it can be much larger.
  When the pool is exhausted the API answers `503` with `Retry-After`, not a slow `500`.
- **Repair.** `python -m scripts.rebuild_cells` rebuilds the rollup from the reports table (run it after bulk loads that bypass the app).

## Sign-in and roles
- Three roles: **citizen** (self-service sign-up with email + password; can report and see their own reports), **officer** (works the queue of
  one area; created by the main admin on the Team page) and **admin** (the main administrator; never self-service; created with
  `python -m scripts.create_admin`, `python -m scripts.make_admin <email>` or `POST /api/v1/admin/users`).
- The sign-in page's Citizen/Administrator tabs only choose which form to show. The server decides the role, and re-checks it on every request:
  the role and the `active` flag are read from the database (not trusted from the token), so demoting or disabling an admin takes effect at once.
- Passwords are hashed with argon2id (off the event loop). Sign-in gives clear reasons (no account for this email / incorrect password / account disabled). This does reveal which emails have accounts, as sign-up already does, so scanning is limited by the per-IP rate limit below (a deliberate trade for clarity),
  and register/login are rate limited per IP (needs Redis; without it only the slow hash limits guessing).
- Tokens are short-lived JWTs (default 8 h) sent as `Authorization: Bearer`, kept in `sessionStorage` (tab-scoped). No cookies, so no CSRF surface;
  the trade-off is that an XSS bug could read the token, which is why user text is never injected as HTML.
- The service API key (`X-API-Key`) still works for scripts and tests, but a signed-in non-admin is refused even if they also send it.
- `REQUIRE_LOGIN_TO_REPORT=true` refuses anonymous reports (off by default for compatibility; turn it on in production). Reports record `reporter_id` when signed in.

Not built: email verification, password reset, "remember me", multi-factor sign-in, token revocation lists (disable the user instead), audit log of admin actions.

## Photos and AI analysis
- **Upload path:** only the person who filed a report (or an admin) can attach photos, max 3 per report, each at most 8 MB. The server decodes and
  **re-encodes** every upload to a bounded JPEG, which drops scripts, malformed trailers and all EXIF metadata (including GPS and camera owner),
  and refuses non-photos, animated images and decompression bombs. The browser also shrinks photos first (less data on slow networks).
- **Storage:** private S3-compatible bucket; admins view photos through 10-minute signed links. Per-person upload rate limit.
- **Where photos go:** with a self-run model (Ollama, vLLM) they never leave your infrastructure. With Groq they are sent to Groq for analysis, which is a privacy decision to make deliberately.
- **Analysis runs off the request path** (`app/events/analysis.py`), so uploads stay fast whatever the model does. Rows are claimed with `SKIP LOCKED`
  (safe on many instances), failures retry with backoff, permanent failures stop, stale claims are released, and a daily cap (`ANALYSIS_MAX_PER_DAY`)
  keeps a spike or abuse from exhausting the model server.
- **The model is untrusted input too.** Report text and any text inside the photo can try to give it instructions; the prompt fences that text off, and
  the answer is validated against a strict schema, bounded in length, and can only produce a severity label shown to staff plus, for serious findings,
  a message to the admin. A small model can still be fooled, which is why findings are labelled assistive and a human decides.
- **Findings are admin-only:** not in the public API, not in "My reports", and the `ReportImageAnalyzed` event is never pushed to the public WebSocket
  or sent to area subscribers (tests cover each).

Not built: virus scanning (re-encoding is the mitigation), automatic deletion of photos when a report is deleted or after a retention period,
consent and retention policy for personal data in photos (worth reviewing against India's data protection law), on-device blurring of faces and number plates.
