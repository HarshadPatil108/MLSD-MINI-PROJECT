"""Application configuration module."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """System configuration settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "development"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Ingestion & Validation
    INDEXED_PG_VERSION: str = "18"
    QUARANTINE_DB_PATH: str = "data/quarantine.db"

    # Task Queue & Broker
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_QUEUE_NAME: str = "incidentops_runs"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
