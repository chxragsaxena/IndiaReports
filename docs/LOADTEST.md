# Load testing and capacity

What was measured, what it showed, what was fixed, and, just as important, what has **not** been proven.

## Rig (read this before quoting any number)
- One Windows 11 laptop. Docker Desktop VM with 8 vCPU and ~3.7 GB RAM running everything: Postgres/PostGIS, Redis, report-service,
  notifier, analytics **and** the load generator (k6 in a container, or a Go program for WebSockets).
- Because the load generator competes for the same CPUs, and Docker-on-Windows networking is slow (a no-op `/health` topped out around
  1,100-1,500 req/s), these numbers are **conservative lower bounds for a Linux server**, and not a prediction of production capacity.
- Data: 300,000 reports (114 MB with indexes) in one Postgres container with its disk on the Docker volume.
- Scripts: `loadtest/k6-mixed.js` (92% reads, 8% writes), `loadtest/k6-single.js` (one endpoint), `services/notifier/loadtest/ws/` (WebSockets).

## What the first run found (it failed)
200 concurrent users, no pauses, cold cache: **22 req/s, p95 24 s, 11% errors.** Three causes, none fixable by "more servers":

| Cause | Evidence | Fix |
|---|---|---|
| Cluster query aggregated the whole table on every cache miss | 0.72 s cold at 300k rows (sequential scan + disk sort); would be ~1 minute at 30M | **Grid rollup table** (`report_cells`): clusters and dashboard now read a few thousand pre-aggregated rows. Cold query 0.036 s and independent of table size |
| Cache stampede: all users recompute an expired key at once | latency collapsed on every TTL boundary | **Single-flight cache** (`app/core/cache.py`): one process computes, the rest wait and read the result. Stores finished JSON, so a hit is one Redis GET |
| Heavy payloads: 439 KB of ORM objects per pins request | pins capped at ~120 req/s even when cached | New **`/reports/pins`** returns only `id, status, lat, lng` for 500 pins: 439 KB (1000 full records) became 61 KB, or 22 KB gzipped. Cached per snapped tile |
| Every write locked the same hot map-cell rows inside its transaction | writes plateaued at 36 req/s regardless of workers | Rollup applied **by a background applier from the outbox**, not in the request. Writes only insert the report + event |
| `FATAL: too many clients` | 205 requests answered 500 once a few workers each held 30 DB connections | Pool 5+5 per worker, `pool_timeout`, Redis pool bounded, **503 + Retry-After** instead of 500 when saturated. Postgres `max_connections=200` in compose |

## Results after the fixes (same rig)
| Test | Before | 2 workers | 6 workers |
|---|---|---|---|
| Writes only (100 users) | 36 req/s | 152 req/s, 0% errors | 210 req/s, 0% errors |
| Reads only (200 users, cold cache) | ~120 req/s (pins) | 583 req/s, 0% errors | 767 req/s, 0% errors |
| Mixed 92/8 (200 users, 60 s) | 22 req/s, 11% errors | 431 req/s, 3.0% errors* | 489 req/s, 2.8% errors* |

\* Every one of those errors is a deliberate **503 shed under saturation** (about 9% of writes in this overloaded mix), with **zero 500s**.
200 users with no think time is far more aggressive than 200 real people.

Mixed-workload latency at 6 workers: clusters p95 453 ms, pins p95 1.15 s, dashboard p95 1.19 s, writes p95 2.2 s. The `p95 < 500 ms`
target used as a threshold in `k6-mixed.js` is **not met** under this overload; it is met for the read endpoints at lower load.

Tripling workers gave 1.15x-1.65x, not 3x, because the rig (load generator + database + Docker networking on 8 shared CPUs) is the limit.
Linear scaling beyond one machine is the design, not something measured here.

### WebSockets (notifier)
5,000 simultaneous map viewers, 8 reports filed inside their viewport:
- Every report reached **all 5,000** viewers (40,000 deliveries), nothing dropped.
- End-to-end latency (request sent to viewer receives): **p50 0.55 s, p95 0.89 s, p99 0.92 s**. Most of that is the report request plus the outbox relay's 0.5 s poll.
- Memory: ~8 MB idle to ~180 MB with 5,000 connections (about 32 KB per connection). The default cap of 50,000 connections per instance therefore needs ~1.7 GB.
- (Run from the host through Docker Desktop's forwarder only ~700 connections succeeded: that is a limit of the rig, so the test runs inside the compose network.)

## What this means for "India scale" (assumptions marked)
Reads dominate and are cacheable, so origin load is set by the number of *distinct* map views, not the number of users:
- Responses carry `Cache-Control: public, max-age=5`, so a CDN absorbs repeats. Origin sees roughly (distinct tile+filter keys) / 5 s.
- *Assuming* 100,000 concurrent map users and one viewport request each per 10 s (about 10,000 req/s at the edge), the origin handles
  the cache misses and the long tail; at roughly 600-800 req/s per 2-6 worker instance on this rig, that is on the order of 10-20 stateless
  instances. Treat this as a sizing starting point, not a promise.
- WebSockets: 100,000 concurrent viewers is 2-4 notifier instances at the 50,000 cap. Fan-out is by map tile, so a report reaches only nearby viewers.
- Writes: a national civic app plausibly peaks at hundreds of reports per second. One Postgres handled 150-210 writes/s here on a laptop disk; production
  hardware is several times that. Beyond it: partition `reports` by state/time and shard the stream by state.

## Not tested / known limits (be honest about these)
- **Never run on more than one machine.** Horizontal scaling of the stateless services is the design (no in-process state that matters; Redis locks
  and `SKIP LOCKED` make background jobs multi-instance safe) but was not demonstrated across nodes.
- **Telegram is a hard fan-out limit**: about 30 messages/s per bot. One event in an area with 100,000 subscribers would take close to an hour.
  Use several bots, digests, or channels for popular areas.
- Postgres failover, read replicas, PgBouncer and CDN configuration are described, not exercised.
- The rollup is **eventually consistent** (about 1-2 s) and can become large: bounded by geography (cells x status x category, up to a few
  million rows at the finest level), not by report count. A hot cell updated by many writers in the applier is a single serialized batch.
- Seeded data is uniform around ten cities; real traffic is heavily skewed to metros.
- No soak test over hours, no test with the notifier or analytics services down.

## Re-running
```
docker compose up -d --build
docker run --rm -i --network indiareports_default -e BASE_URL=http://report-service:8000 -e VUS=200 grafana/k6 run - < loadtest/k6-mixed.js
docker run --rm -i --network indiareports_default -e BASE_URL=http://report-service:8000 -e MODE=write -e VUS=100 -e DURATION=15s grafana/k6 run - < loadtest/k6-single.js
cd services/notifier && go run ./loadtest/ws -n 5000   # from inside the network, see the file header
```
Load a realistic table first (the test used 300,000 rows) and run `python -m scripts.rebuild_cells` after bulk loads that bypass the app.
