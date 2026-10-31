import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "India Reports API"
    DEBUG: bool = False

    DATABASE_URL: str

    # Optional. When unset the service still works; events simply stay in the outbox.
    REDIS_URL: str | None = None

    # Required to change a report's status. When unset, the endpoint is disabled.
    ADMIN_API_KEY: str | None = None

    # Signs the acknowledge links sent to officers. Falls back to ADMIN_API_KEY.
    ACK_SECRET: str | None = None

    # The responsible officer must RESOLVE a report within this long of it being assigned
    # (7 days). Past that it escalates to the main admin. Acknowledging does not stop the clock.
    ESCALATION_AFTER_SECONDS: int = 7 * 24 * 3600
    ESCALATION_CHECK_SECONDS: int = 60

    # A resolved report stays on the public map this long, so the person who reported it can
    # check the fix (confirm it, or reopen it), then it leaves the map.
    RESOLVED_VISIBLE_SECONDS: int = 3 * 24 * 3600
    LIFECYCLE_CHECK_SECONDS: int = 60

    # ---- Email (citizen "resolved" notices, officer assignment alerts) ------------------
    # Providers: "resend" (HTTPS API; works on hosts that block SMTP, like Render's free tier),
    # "smtp", "log" (print to the server log; development), "off". Empty means: resend if
    # RESEND_API_KEY is set, else smtp if SMTP_HOST is set, else off.
    EMAIL_PROVIDER: str = ""
    EMAIL_FROM: str = "IndiaReports <onboarding@resend.dev>"
    RESEND_API_KEY: str | None = None
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = True
    EMAIL_MAX_ATTEMPTS: int = 6
    # The website's address, used for links inside emails (for example https://example.vercel.app).
    PUBLIC_APP_URL: str = ""

    # Signs sign-in tokens. Falls back to ADMIN_API_KEY so a deployment that only set
    # that still works; set a dedicated long random value in production.
    JWT_SECRET: str | None = None
    JWT_TTL_SECONDS: int = 8 * 3600
    AUTH_RATE_LIMIT_PER_MINUTE: int = 20

    # When true, only signed-in people can file reports (anonymous reports are refused).
    # Off by default so existing clients keep working; turn it on in production.
    REQUIRE_LOGIN_TO_REPORT: bool = False

    # ---- Photos -----------------------------------------------------------------
    # S3-compatible object storage (MinIO locally, S3 / Cloudflare R2 in production).
    # Leave S3_ENDPOINT_URL unset to turn photo uploads off.
    S3_ENDPOINT_URL: str | None = None
    # Address a browser can reach, used in the short-lived links admins view photos
    # through. Defaults to S3_ENDPOINT_URL (differs inside docker networks).
    S3_PUBLIC_URL: str | None = None
    S3_BUCKET: str = "indiareports-photos"
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_REGION: str = "auto"

    MAX_IMAGES_PER_REPORT: int = 3
    MAX_UPLOAD_BYTES: int = 8 * 1024 * 1024
    UPLOAD_RATE_LIMIT_PER_MINUTE: int = 20
    IMAGE_URL_TTL_SECONDS: int = 600

    # Spoken descriptions (stored next to photos, transcribed by the ai-service).
    MAX_VOICE_BYTES: int = 3 * 1024 * 1024
    MAX_VOICE_SECONDS: int = 90
    MAX_VOICE_NOTES_PER_REPORT: int = 1

    # ---- WhatsApp reporting (Twilio) ---------------------------------------------------
    # Set both to turn it on. WHATSAPP_WEBHOOK_URL is the exact public address Twilio posts to
    # (https://<api host>/api/v1/whatsapp/webhook): the signature check is computed over it.
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_ACCOUNT_SID: str | None = None  # only needed to download voice notes
    WHATSAPP_WEBHOOK_URL: str = ""
    WHATSAPP_REPORTS_PER_DAY: int = 10  # per phone number
    WHATSAPP_GEOCODE: bool = True  # look up the street and city from the shared location

    # ---- AI service ---------------------------------------------------------------
    # The ai-service reads uploaded photos from the event stream, analyses them with a vision
    # model and posts the findings back to /internal/images/{id}/analysis. This key proves the
    # caller is that service. Unset: the endpoint is closed and photos get no findings.
    INTERNAL_API_KEY: str | None = None

    CORS_ORIGINS: str = "*"

    # Connection budget: workers x instances x (DB_POOL_SIZE + DB_MAX_OVERFLOW) must stay
    # below the database max_connections (default 100), with room for other services.
    # Behind PgBouncer this can be much larger.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    # How long a request waits for a free connection before answering 503.
    DB_POOL_TIMEOUT: int = 5
    REDIS_MAX_CONNECTIONS: int = 100

    # Hard cap on rows returned by the full-record list endpoint.
    MAX_REPORTS_PER_QUERY: int = 1000

    # Hard cap on pins returned for one map viewport (the response says if it truncated).
    MAX_PINS_PER_QUERY: int = 500

    # Creating reports: requests per IP per minute.
    RATE_LIMIT_PER_MINUTE: int = 30

    CLUSTER_CACHE_TTL_SECONDS: int = 30
    DASHBOARD_CACHE_TTL_SECONDS: int = 10

    EVENT_STREAM: str = "reports.events"
    EVENT_STREAM_MAXLEN: int = 1_000_000

    model_config = SettingsConfigDict(
        env_file=".env",
        # Render mounts "Secret Files" here, one file per setting named after it (JWT_SECRET, ...).
        # Environment variables still win over these files.
        secrets_dir="/etc/secrets" if os.path.isdir("/etc/secrets") else None,
        extra="ignore"
    )


settings = Settings()
