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
Be clear about what is designed in versus what has been verified. The design below is built to scale horizontally; it has **not** been load-tested at 100M users, and nobody can honestly claim that from a laptop. A load-test script and measured numbers live in `docs/LOADTEST.md` once stage 6 is done.

1. **Stateless services.** No in-process state that matters. Run N copies behind a load balancer.
2. **Read path is cheap.** Map views are bounding-box queries on a GiST index. Cluster and dashboard responses are cached in Redis with short TTLs, and the cache key snaps the viewport to a grid so many users share entries.
3. **Bounded responses.** Report list queries have a hard row cap; clusters aggregate in the database. No endpoint returns an unbounded result set.
4. **Write path is decoupled.** A report insert plus its outbox row are one DB transaction. A relay publishes to the stream, so a Redis outage never loses an event and never blocks report creation.
5. **Fan-out by geography.** WebSocket clients join geo-tile rooms for their viewport; a new report is sent only to clients in that tile, not to everyone. Notifier instances share state through Redis Pub/Sub so any instance can serve any client.
6. **Rollups, not scans.** Analytics updates counters per event (upserts into rollup tables). Dashboards never scan the raw reports table.
7. **Abuse protection.** Per-IP rate limiting on writes via Redis; admin-only status changes behind an API key.
8. **Database path to scale.** Connection pooling (use PgBouncer in front of Postgres), read replicas for the read-heavy endpoints, and partitioning `reports` by time (or state) once row counts reach hundreds of millions.

## Failure behaviour
- Redis down: report-service keeps accepting and serving reports (events wait in the outbox).
- notifier or analytics down: nothing user-facing breaks except live pins/stats; they catch up from the stream when they return.
