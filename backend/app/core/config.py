from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_KEY = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Invoice & Expense Reconciliation Engine"
    environment: str = "development"  # development | test | production
    database_url: str = "sqlite:///./data/app.db"
    secret_key: str = INSECURE_DEFAULT_KEY
    access_token_minutes: int = 60
    storage_dir: str = "./data/storage"
    max_upload_mb: int = 15
    max_pages: int = 20
    ocr_provider: str = "tesseract"
    ocr_languages: str = "eng"
    ocr_timeout_seconds: int = 60
    # inline = run in the request, background = FastAPI BackgroundTasks, celery = Redis/Celery worker
    processing_mode: str = "background"
    job_max_attempts: int = 3
    job_retry_backoff_seconds: float = 1.0
    cors_origins: str = "http://localhost:5173"
    celery_broker_url: str = "redis://localhost:6379/0"
    rate_limit_per_minute: int = 30
    static_dir: str | None = None
    auto_create_tables: bool = True

    def validate_for_production(self) -> None:
        if self.environment == "production" and self.secret_key == INSECURE_DEFAULT_KEY:
            raise RuntimeError("SECRET_KEY must be set to a strong random value in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
