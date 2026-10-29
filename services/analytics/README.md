# analytics

Go service. Consumes `reports.events` (its own consumer group) and keeps small rollup tables in `analytics_db`. It never stores raw reports, so every query is cheap regardless of report volume.

## Endpoints
- `GET /v1/summary?days=30`: totals, resolution rate, average time to resolve, by category, top states
- `GET /v1/trends?days=30&state=&category=`: daily created/resolved series (IST days)
- `GET /v1/leaderboard?by=state|city&days=30&min_reports=5`: ranked by resolution rate, small samples excluded
- `GET /v1/hotspots?limit=10&min_count=5`: ~5 km cells whose last-24h volume is well above their own previous-7-day baseline
- `GET /healthz`, `GET /readyz`

Responses are cached in-process for 15 s (bounded), so a burst of identical dashboard requests costs one query per instance.

## Correctness
Each event is applied in one transaction together with an insert into `processed_events`, so redelivery from the stream never double counts. Entries that keep failing go to `reports.events.dead`.

## Known limits
- Only events after the stream began are counted (no backfill of pre-existing rows).
- A report reopened after RESOLVED is not subtracted from the resolved count.

## Tests
`go test ./...`
