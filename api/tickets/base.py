from abc import ABC, abstractmethod

from pydantic import BaseModel


class TicketRequest(BaseModel):
    """Единый язык домена — то, что бизнес-слой просит у тикет-системы."""

    title: str
    description: str


class TicketCreated(BaseModel):
    """Результат создания: внутренний ID системы + человекочитаемый ключ."""

    external_id: str
    display_key: str


class TicketSystem(ABC):
    """Контракт тикет-системы. Все реализации (JSM, Zendesk, Usedesk) обязаны его поддерживать."""

    @abstractmethod
    async def create(self, req: TicketRequest) -> TicketCreated:
        ...
