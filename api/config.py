from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
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


class RagSettings(BaseSettings):
    model_config = DatabaseSettings.model_config

    rag_enabled: bool = False
    rag_service_token: SecretStr | None = Field(default=None, min_length=32)
    rag_qdrant_url: AnyHttpUrl = AnyHttpUrl("http://qdrant:6333")
    rag_qdrant_api_key: SecretStr | None = None
    rag_collection: str = Field(default="bars_docs_qwen3_v1", pattern=r"^[a-zA-Z0-9_\-]+$")
    rag_embedding_base_url: AnyHttpUrl | None = None
    rag_embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    rag_embedding_api_key: SecretStr | None = None
    rag_luna_base_url: AnyHttpUrl | None = None
    rag_luna_model: str = "gpt-6-luna"
    rag_luna_api_key: SecretStr | None = None
    rag_max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def check_rag_settings(self):
        if self.rag_enabled and not all(
            (self.rag_service_token, self.rag_embedding_base_url, self.rag_luna_base_url)
        ):
            raise ValueError(
                "RAG_SERVICE_TOKEN, RAG_EMBEDDING_BASE_URL and RAG_LUNA_BASE_URL are required"
            )
        return self
