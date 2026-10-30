from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The event stream the report-service publishes to, and our consumer group on it.
    REDIS_URL: str | None = None
    EVENT_STREAM: str = "reports.events"
    CONSUMER_GROUP: str = "ai-service"

    # Where results are sent, and the shared key that proves we are allowed to.
    REPORT_SERVICE_URL: str = "http://localhost:8000"
    INTERNAL_API_KEY: str | None = None

    # Photos are read from the same S3-compatible storage the report-service writes to.
    S3_ENDPOINT_URL: str | None = None
    S3_BUCKET: str = "indiareports-photos"
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_REGION: str = "auto"

    # ---- Vision model (photo analysis) -----------------------------------------------
    # Providers: groq | openai_compatible (Ollama, vLLM...) | mock | off.
    # Empty means: openai_compatible if ANALYSIS_BASE_URL is set, else groq if GROQ_API_KEY is set, else off.
    ANALYSIS_PROVIDER: str = ""
    GROQ_API_KEY: str | None = None
    ANALYSIS_BASE_URL: str | None = None
    ANALYSIS_API_KEY: str | None = None
    ANALYSIS_MODEL: str = ""
    # The model for reading report text (language, translation, urgency, spam). Empty picks a small
    # fast open-weight text model: gpt-oss-20b on Groq, qwen3:4b on Ollama.
    TRIAGE_MODEL: str = ""
    # The model that compares a before and an after photo. Empty uses ANALYSIS_MODEL.
    VERIFY_MODEL: str = ""
    VERIFY_MAX_PER_DAY: int = 1000
    ANALYSIS_TIMEOUT_SECONDS: float = 240.0
    ANALYSIS_CONCURRENCY: int = 1
    ANALYSIS_MAX_PER_DAY: int = 2000
    ANALYSIS_MAX_ATTEMPTS: int = 3
    TRIAGE_MAX_PER_DAY: int = 20000


settings = Settings()
