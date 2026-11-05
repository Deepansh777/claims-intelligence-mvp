from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Repo-root .env, so scripts and tests work from backend/; real env vars still win.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )

    environment: str = "development"
    database_url: str
    # Read-only login role for LLM-generated SQL; created by the Alembic migration.
    analytics_database_url: str
    chat_retention_days: int = 15
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
