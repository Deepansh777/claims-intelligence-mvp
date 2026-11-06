from pathlib import Path

from pydantic import SecretStr
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
    dashboard_retention_days: int = 30
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-6.1-sol"
    openai_timeout_seconds: int = 120
    cors_origins: list[str] = ["http://localhost:5173"]
    # shortcut: single fixed user until Cognito; every query is still scoped by user id.
    app_user_id: str = "local-user"
    app_user_is_admin: bool = True


settings = Settings()
