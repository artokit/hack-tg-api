from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )

    database_url: SecretStr


class Settings(DatabaseSettings):
    agent_api_token: SecretStr = Field(min_length=1)
    chat_base_url: AnyHttpUrl
    chat_model: str = Field(min_length=1)
    chat_api_key: SecretStr | None = None
    chat_context_window: int = Field(ge=1024)
