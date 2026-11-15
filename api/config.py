from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
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


class RedisSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    rag_redis_url: SecretStr = SecretStr("redis://127.0.0.1:6380/0")


class JiraSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    jira_base_url: str = "https://barsgroup.atlassian.net"
    jira_email: str = ""
    jira_api_token: SecretStr = SecretStr("")
    jsm_service_desk_id: str = "1"
    jsm_request_type_id: str = "1"


class ConfluenceSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    confluence_base_url: str = "https://barsdocs.atlassian.net/wiki"
    confluence_email: str = ""
    confluence_api_token: SecretStr = SecretStr("")


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


class EmbeddingSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    embedding_base_url: AnyHttpUrl | None = None
    embedding_api_key: SecretStr | None = None


class FileSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    file_service_url: AnyHttpUrl = AnyHttpUrl("http://file-service:3000")
    rag_files_public_url: AnyHttpUrl = AnyHttpUrl("https://api.cheremha.ru")
