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

    # A report left unacknowledged this long is escalated to the main admin (7 days).
    ESCALATION_AFTER_SECONDS: int = 7 * 24 * 3600
    ESCALATION_CHECK_SECONDS: int = 60

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

    # ---- AI photo analysis (open-weight vision model) ------------------------------
    # Providers:
    #   "groq"              hosted open-weight models through Groq's OpenAI-compatible API
    #                       (same GROQ_API_KEY as PullWise). Photos are sent to Groq.
    #   "openai_compatible" a server you run: Ollama, vLLM, llama.cpp, LM Studio. Photos
    #                       stay on your infrastructure.
    #   "mock"              clearly labelled demo output with no model at all.
    #   "off"               no analysis.
    # Empty means: openai_compatible if ANALYSIS_BASE_URL is set, else groq if GROQ_API_KEY
    # is set, else off.
    ANALYSIS_PROVIDER: str = ""
    GROQ_API_KEY: str | None = None
    ANALYSIS_BASE_URL: str | None = None  # for openai_compatible (Ollama on the host, vLLM...)
    ANALYSIS_API_KEY: str | None = None  # only if your own server requires one
    # Empty picks a default that can read images: a Llama 4 Scout on Groq, a Qwen3-VL on
    # Ollama. Text-only models (for example gpt-oss or llama3) cannot analyse photos.
    ANALYSIS_MODEL: str = ""
    # Local CPU inference can take a minute or more per photo; hosted answers take seconds.
    ANALYSIS_TIMEOUT_SECONDS: float = 240.0
    ANALYSIS_CONCURRENCY: int = 1
    # Hard cap on analyses per day, so a spike (or abuse) cannot exhaust your quota or GPU.
    ANALYSIS_MAX_PER_DAY: int = 2000
    ANALYSIS_MAX_ATTEMPTS: int = 3

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
        extra="ignore"
    )


settings = Settings()
