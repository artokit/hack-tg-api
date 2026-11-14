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


class JiraSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    jira_base_url: str = "https://barsgroup.atlassian.net"
    jira_email: str = ""
    jira_api_token: SecretStr = SecretStr("")
    jsm_service_desk_id: str = "1"
    jsm_request_type_id: str = "1"


_jira = JiraSettings()
TICKET_ROUTES: dict[str, dict] = {
    "default": {
        "system": "jsm",
        "base_url": _jira.jira_base_url,
        "email": _jira.jira_email,
        "api_token": _jira.jira_api_token.get_secret_value(),
        "service_desk_id": _jira.jsm_service_desk_id,
        "request_type_id": _jira.jsm_request_type_id,
    },
}


class AuthSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    jwt_secret: SecretStr = Field(min_length=32)
    jwt_access_token_expire_minutes: int = Field(default=60, ge=1)


class InviteSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    telegram_bot_username: str | None = Field(
        default=None, min_length=5, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_]*$"
    )
    bot_api_token: SecretStr | None = Field(default=None, min_length=32)
