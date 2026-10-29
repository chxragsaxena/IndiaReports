# notifier

Go service. Consumes `reports.events` from Redis Streams and (1) pushes live pins to map clients over WebSocket, (2) sends alerts to area subscribers (Telegram).
Owns `notifier_db` (subscriptions, deliveries).

## Run
`docker compose up --build notifier` from the repo root. Config via env:

| Var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | required | postgres URL for notifier_db |
| `REDIS_URL` | required | stream + rate limiting |
| `PORT` | 8100 | |
| `TELEGRAM_BOT_TOKEN` | empty | empty = alerts are logged, not sent |
| `APP_URL` | https://indiareports.vercel.app | link used in alert text |
| `CORS_ORIGINS` | `*` | comma-separated; also checked for WebSocket origins |
| `MAX_CONNECTIONS` | 50000 | WebSocket cap per instance |
| `SEND_WORKERS` | 16 | parallel sends per event |
| `TELEGRAM_RATE_PER_SEC` | 25 | per instance; Telegram allows ~30/s per bot overall |

## WebSocket `GET /ws`
Server -> client: `{"type":"ready"}` on connect.
Client -> server, whenever the map moves (debounce ~300 ms):
```json
{"type":"viewport","bbox":[west,south,east,north],"zoom":11.2}
```
Server -> client:
- `{"type":"report","event":"ReportCreated"|"ReportStatusChanged","report":{...}}` when `zoom >= 11` and the report is inside the viewport.
- `{"type":"refresh"}` when `zoom < 11` and a report landed inside the viewport (at most once per 3 s). Re-fetch clusters from report-service.

A client that cannot keep up is disconnected rather than allowed to slow others. Reconnect with backoff and resend the viewport.

## HTTP
- `POST /v1/subscriptions` body: `{channel:"telegram", chat_id, kind: pincode|city|state|radius, pincode | city+state | state | latitude+longitude+radius_km(0.5-50), category?}` -> 201
- `GET /v1/subscriptions?chat_id=` -> list
- `DELETE /v1/subscriptions/{id}?chat_id=` -> 204
- `GET /v1/stats`, `GET /healthz`, `GET /readyz`

## Delivery guarantees
At-least-once from the stream, made effectively-once per subscriber by a unique `(subscription_id, event_id)` row. Failed entries are retried (XAUTOCLAIM), and after `MAX_DELIVERY_TRIES` go to `reports.events.dead`.

## Known limits
- Telegram only messages users who have started the bot; a subscription for anyone else fails permanently and is marked `failed`.
- One consumer handles up to a few hundred events/s. Scale out by adding instances (the consumer group shares the work); beyond that, shard the stream by state.

## Tests
`go test -race ./...` (unit) and, against a running stack, `go test -tags integration ./integration/` (see the file header).

## Direct messages (area officer / escalation)
Events may carry a `recipient` (the responsible officer, or the admin on `ReportEscalated`). The notifier sends that person a direct
message containing the acknowledge link, idempotently per `(event_id, chat_id)` in `direct_deliveries`. Recipient details are never
forwarded over the WebSocket.
