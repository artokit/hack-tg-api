from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel


class TicketRequest(BaseModel):
    """Единый язык домена — то, что бизнес-слой просит у тикет-системы."""

    title: str
    description: str


@dataclass(frozen=True)
class TicketCreated:
    external_id: str
    external_key: str


@dataclass(frozen=True)
class TicketAttachment:
    issue_id_or_key: str
    comment_id: str
    filename: str
    public: bool


class TicketSystem(ABC):
    """Контракт тикет-системы. Все реализации (JSM, Zendesk, Usedesk) обязаны его поддерживать."""

    @abstractmethod
    async def create(self, req: TicketRequest) -> TicketCreated:
        ...

    @abstractmethod
    async def attach_file(
        self,
        issue_id_or_key: str,
        filename: str,
        content: bytes,
        content_type: str,
        public: bool,
    ) -> TicketAttachment:
        ...
