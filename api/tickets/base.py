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
    external_url: str | None = None


class TicketSystem(ABC):
    """Контракт тикет-системы. Все реализации (JSM, Zendesk, Usedesk) обязаны его поддерживать."""

    @abstractmethod
    async def create(self, req: TicketRequest) -> TicketCreated:
        ...

    @abstractmethod
    async def find_by_reference(self, reference: str) -> TicketCreated | None:
        ...

    @abstractmethod
    async def get_ticket_url(self, external_id: str) -> str:
        ...
