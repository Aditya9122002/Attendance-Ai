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
    gemini_model: str = "gemini-3.1-flash-lite"
    database_url: str = "sqlite+aiosqlite:///./attendance.db"
    # Telephony. All optional: the app runs without them, the phone routes then refuse to serve.
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None  # a Twilio number, E.164, for example +1415...
    public_base_url: str | None = None  # where Twilio reaches us, e.g. https://abc.ngrok-free.app


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance per process."""
    return Settings()
