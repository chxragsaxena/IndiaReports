from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "India Reports API"
    DEBUG: bool = False

    DATABASE_URL: str

    # Optional. When unset the service still works; events simply stay in the outbox.
    REDIS_URL: str | None = None

    # Required to change a report's status. When unset, the endpoint is disabled.
    ADMIN_API_KEY: str | None = None

    CORS_ORIGINS: str = "*"

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Hard cap on rows returned by the map list endpoint.
    MAX_REPORTS_PER_QUERY: int = 1000

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
