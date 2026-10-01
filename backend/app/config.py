"""Application settings, loaded from environment variables and an optional .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings.

    Purpose: single source of truth for configuration.
    Input: environment variables (and .env in development).
    Output: an immutable-by-convention settings object.
    Dependencies: none.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    gemini_api_key: SecretStr | None = None
    database_url: str = "sqlite+aiosqlite:///./attendance.db"


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance per process."""
    return Settings()
