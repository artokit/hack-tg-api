from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            Path(__file__).resolve().parent / ".env",
            Path(__file__).resolve().parents[1] / ".env",
        ),
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )

    database_url: SecretStr


class AuthSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    jwt_secret: SecretStr = Field(min_length=32)
    jwt_access_token_expire_minutes: int = Field(default=60, ge=1)
