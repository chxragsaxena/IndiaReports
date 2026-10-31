# IndiaReports

Report civic issues on a map of India, watch them appear live, and see which ones get fixed. Reports are routed to the officer responsible
for that area and escalate to an administrator if nobody acknowledges them.

```
React + MapLibre (Vercel)
   |
   +--> report-service  (Python/FastAPI, PostGIS)   reports, map clusters/pins, areas, officers, escalation
   +--> notifier        (Go)                        live WebSocket pins, Telegram alerts
   +--> analytics       (Go)                        trends, hotspots, resolution leaderboard
   +--> ai-service      (Python)                    photo analysis with open-weight vision models
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
Service ports: report-service 8000, notifier 8100, analytics 8200, ai-service 8300 (change with `REPORT_PORT`, `NOTIFIER_PORT`, `ANALYTICS_PORT`, `AI_PORT`, `POSTGRES_PORT`, `REDIS_PORT`).
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
- **ai-service**: `REDIS_URL`, `REPORT_SERVICE_URL`, `INTERNAL_API_KEY` (the same value as report-service), `S3_*` (read access to the photo storage), and the model settings under "Photos and AI analysis" (`GROQ_API_KEY` or `ANALYSIS_BASE_URL`, `ANALYSIS_MODEL`). report-service needs only `INTERNAL_API_KEY`.
- **frontend (Vercel)**: `VITE_API_URL`, `VITE_NOTIFIER_URL`, `VITE_ANALYTICS_URL` (the last two optional), `VITE_MAP_STYLE`, `VITE_TELEGRAM_BOT`.

## Deploying (Render + Vercel)
- Make the Render Start Command `python -m scripts.migrate && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. The script migrates a new database,
  upgrades a tracked one, and stamps an old untracked one before upgrading, so it is safe on every deploy.
- **One-step setup:** `render.yaml` in the repo root describes every service (API, ai-service, notifier, analytics) and the Redis instance. In Render choose
  New > Blueprint, pick this repo, and fill in the prompted values (the Neon URLs, a Groq key, storage and email keys). The header of that file lists what each
  needs and its limits: the database stays on Neon, free services sleep (and one workspace only gets about 750 free hours a month), and the Redis instance must
  keep `noeviction`. If the API already exists, delete its block before applying.
- Create two extra databases next to `neondb` in Neon for the Go services: `notifier_db` and `analytics_db` (Neon console > Databases), and use their direct (not `-pooler`) URLs.
- Free tiers sleep, so the first request after idle is slow. The background workers only run while awake: for a real demo give the ai-service and notifier a paid plan.
- Set `ADMIN_API_KEY` (and ideally a separate `ACK_SECRET`) to long random values.
- `frontend/vercel.json` rewrites client routes so deep links such as `/ack?...` work.

## Accounts
Citizens sign up on the site. Create the first administrator from the command line (it prompts for the password, or set `ADMIN_PASSWORD`):
```
docker compose run --rm --entrypoint python report-service -m scripts.create_admin you@yourdomain.org "Your Name"
```
Then sign in on the **Administrator** tab. Set `JWT_SECRET` to a long random value and `REQUIRE_LOGIN_TO_REPORT=true` in production.

On a host with no shell (Render free tier), run `python -m scripts.make_admin you@example.org [new-password]` from the Start Command (creates or resets the account with that password; `python -m scripts.delete_user you@example.org` removes one)
(before `uvicorn`) and restart.

## How reports are handled
1. A citizen reports an issue. It goes to the **officer of the smallest area (polygon) it falls in**, who is emailed. If no area contains it, it goes to the main administrator.
2. The officer must **resolve it within 7 days** (`ESCALATION_AFTER_SECONDS`). Otherwise it is escalated to the main administrator. (Further levels up to
   city, district and state agencies are described in `docs/ARCHITECTURE.md` but not built.)
3. When the officer marks it resolved (with a note for the citizen), the citizen is **emailed** and the report **stays on the map for 3 days**
   (`RESOLVED_VISIBLE_SECONDS`) so they can check it. They can confirm the fix or reopen it. Then it leaves the map; it is kept in "My reports".

**Same problem, reported twice.** While filing, the form checks for an open report of the same kind within 150 m that is worded alike (or within 30 m, whatever the wording) and offers
**Me too** instead of a copy. Each signed-in person counts once, the page shows "N people affected", and everyone who said "me too" is emailed when it is fixed. To file anyway, the person must first tick "I have checked, and my problem is different". If a copy is filed
anyway, staff see "may be a copy of an older report"; nothing is hidden or merged automatically. This needs no AI model: it is a map-distance and word-overlap check, so it also
works offline of any model (reports in different languages only match by distance).

**Scorecards.** The public **Scorecards** page ranks each area on the share of reports resolved within the deadline (reports still inside it are not counted against anyone), the median time to fix, how often the reporter disputed the fix, and what is open or escalated. Reports stay counted against the area they were routed to even after they escalate, and spam is left out. Counts only: no report text is shown.

The main administrator manages officers and areas on the **Team** page (an area is a GeoJSON polygon, which you can draw at geojson.io).
Officers sign in on the **Administrator** tab and see only their own area's queue.

## Email
Citizens are emailed when their report is resolved; officers when a report arrives in their area or is reopened; the administrator on escalation.
Set `PUBLIC_APP_URL` (your Vercel address) so the emails link back to the site, then choose a provider:
- `RESEND_API_KEY` (and `EMAIL_FROM`): HTTPS API from resend.com. **Use this on Render's free tier, which blocks SMTP.** Until you verify a domain, Resend only
  delivers to your own account's address, which is enough for a demo.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`: any SMTP server (not on Render free).
- `EMAIL_PROVIDER=log`: print emails in the server log (the local default).
With none set, no email is sent and nothing else changes. Failed emails are retried for hours before giving up.

## WhatsApp reporting
People can report by WhatsApp: send a message or a voice note, then share the location (+ > Location). The report is filed like any other, as an anonymous report,
and a voice note goes through the same Whisper transcription as one recorded on the site. Replies are written by the server as TwiML, so no outbound WhatsApp
credentials are needed. The phone number is never stored (only a hash for the 15-minute conversation and a daily counter, 10 reports a day per number).
Not built: telling the person on WhatsApp when it is fixed (needs Twilio's sender API and a stored number).

To try it free, use Twilio's **WhatsApp sandbox** (Twilio Console > Messaging > Try it out > Send a WhatsApp message): join it from your phone with the code shown, then
set "When a message comes in" to `https://<your API host>/api/v1/whatsapp/webhook` (HTTP POST). On the API set:
- `TWILIO_AUTH_TOKEN`: from the Twilio console. Requests are only accepted if their signature matches it.
- `WHATSAPP_WEBHOOK_URL`: exactly the address above (the signature is computed over it).
- `TWILIO_ACCOUNT_SID`: optional, only to download voice notes.
The sandbox is for testing; a public number needs a Twilio WhatsApp sender approved by Meta, which is a paid, reviewed process.

## Photos and AI analysis
Citizens can attach up to 3 photos to a report. Photos are private: only the reporter and administrators can see them, through short-lived signed links.
An open-weight vision model looks at each photo and reports findings to the administrator (what it shows, severity, hazards, whether the category fits,
a suggested action). Serious findings (high or critical severity, or inappropriate content) also message the admin on Telegram.
**Different open models for different jobs** (each set by its own env var, so a slow one never holds up another):

| Job | Default model (Groq) | Setting |
|---|---|---|
| Photo analysis | `qwen/qwen3.8-27b` (vision) | `ANALYSIS_MODEL` |
| Report text: language, English translation, urgency, spam | `openai/gpt-oss-20b` (small, fast) | `TRIAGE_MODEL` |
| Before/after fix check: is the repair photo the same place with the problem gone? | the vision model (own prompt) | `VERIFY_MODEL` (empty uses `ANALYSIS_MODEL`) |
| Voice notes: speech to text in any Indian language | `whisper-large-v3` (open-weight Whisper) | `TRANSCRIBE_MODEL`, `TRANSCRIBE_BASE_URL` |

A staff member sees the translation, urgency and a possible-spam flag next to each report. The model is told to treat report text as untrusted data, and its output is bounded before it is stored.

**Checking a fix.** On a report's detail panel, staff can add up to 2 *repair photos*. The vision model compares each with the reporter's original photo and says
*looks fixed*, *partly fixed*, *not fixed* or *cannot tell*, with what is still wrong and whether it looks like the same place. It is an assistive hint for the
supervisor, shown to staff only; it never changes a report's status by itself. If the reporter sent no photo, the repair photo is judged on its own.

**Voice reports.** A signed-in citizen can record up to a minute instead of typing (any Indian language). The recording is stored like a photo (so it needs the
same object storage), the ai-service transcribes it with Whisper, and the transcript is shown to staff next to the original recording so they can check it. If the
person only spoke, the transcript becomes the report's description and goes through text triage like typed text; a typed description is never overwritten.
Recordings are checked by their real bytes (webm, ogg, mp4, wav, mp3), capped at 3 MB, and are visible to staff only. Set `TRANSCRIBE_BASE_URL` to use your own
Whisper server (faster-whisper-server, vLLM) instead of Groq, so audio stays on your infrastructure. Accuracy for each Indian language has not been measured here:
that is what the staff-visible original recording is for.

This runs in its own service, **ai-service** (`services/ai`), which reads upload events from the Redis stream and posts findings back to the report-service
(set the same `INTERNAL_API_KEY` on both). If it is down, uploads still work and photos wait for findings.
Copy `.env.example` to `.env` to see every setting.

**Two ways to run the model** (both use the OpenAI-compatible chat API, as PullWise does):

| | Groq (hosted) | Your own server (Ollama, vLLM, llama.cpp) |
|---|---|---|
| Setup | Set `GROQ_API_KEY` (free key at console.groq.com/keys, the same one PullWise uses) | Set `ANALYSIS_BASE_URL` (and `ANALYSIS_MODEL`) |
| Default model | `qwen/qwen3.8-27b`, an open-weight Qwen that accepts images (checked live) | `qwen3-vl:4b` (Qwen3-VL is among the strongest open vision families) |
| Hardware | none; answers in seconds | a laptop can run a small one slowly; a GPU server gives real quality |
| **Where photos go** | **to Groq's servers** | **stay on your infrastructure** |

**Privacy: with Groq, citizens' photos leave your infrastructure.** Check Groq's data terms for the plan you use, and tell your users. If photos must stay with you, use your own server.
Remove people and number plates where you can; the model is also asked to flag them.

**The model must be able to read images.** Text-only models, including `openai/gpt-oss-120b` (PullWise default) and `llama3`, cannot analyse photos. Hosted catalogues change (Llama 4 Scout, the first default here, vanished from Groq): list what your key can use with `GET https://api.groq.com/openai/v1/models`.
Override with `ANALYSIS_MODEL` if Groq or your server offers a better vision model; exact names change over time, so check the provider's model list.

Local Ollama example, using the bundled container (a multi-GB download, and Docker needs several GB of RAM):
```
docker compose --profile ai up -d ollama
docker compose exec ollama ollama pull qwen3-vl:2b
# in .env:   ANALYSIS_BASE_URL=http://ollama:11434/v1   ANALYSIS_MODEL=qwen3-vl:2b
docker compose up -d ai-service
```
Without any model, `ANALYSIS_PROVIDER=mock` shows the whole flow with clearly labelled demo findings (and never messages anyone); leave everything unset to turn analysis off.

**Reliability (the same habits as PullWise):** strict JSON-schema output with a fallback for servers that cannot enforce it, one repair attempt when the answer is invalid,
a check on why the model stopped, and rate-limit (429) handling that waits for the time the server asks (capped at 30 s, two retries) before leaving the photo for a later retry.
A daily cap (`ANALYSIS_MAX_PER_DAY`) protects your free-tier quota.

**Photo storage** is any S3-compatible service: the compose file runs an open-source one for local use; in production set `S3_ENDPOINT_URL`, `S3_BUCKET`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY` (and `S3_PUBLIC_URL` if browsers reach it at a different address) for S3 or Cloudflare R2. Leave `S3_ENDPOINT_URL` unset to turn uploads off.

**Treat findings as assistive.** Open models are weaker than the best frontier models, and nobody has measured this one's accuracy on Indian civic photos.
Before letting severity drive alerts in production, collect a set of real photos with known answers and check the model against it.
