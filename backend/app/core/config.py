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
