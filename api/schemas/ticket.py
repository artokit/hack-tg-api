from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    """Контракт ручки POST /tickets (то, что присылает бот)."""

    title: str = Field(min_length=5, max_length=255)
    description: str
    category: str = "default"
    author_name: str | None = None
    support_request_id: UUID | None = None


class TicketRead(BaseModel):
    """Ответ API по заявке."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    category: str
    system: str
    status: str
    external_id: str | None
    external_key: str | None


class TicketRecipientRead(BaseModel):
    telegram_chat_id: str
