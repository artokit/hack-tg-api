from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )

    bot_token: SecretStr = Field(min_length=1)
    agent_api_token: SecretStr = Field(min_length=1)
    api_url: AnyHttpUrl = Field(default="http://127.0.0.1:8000")
    ADMIN_IDS: list[int] = Field(default_factory=list)
