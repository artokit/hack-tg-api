from sqlalchemy.ext.asyncio import AsyncSession

from config import TICKET_ROUTES
from models.tickets import Ticket
from schemas.ticket import TicketCreate
from tickets.base import TicketRequest
from tickets.registry import build_adapter


class TicketService:
    """Бизнес-слой: создаёт заявку у себя и синхронизирует с тикет-системой.

    Не знает, какая система под капотом — работает через контракт TicketSystem.
    """

    async def create(self, session: AsyncSession, data: TicketCreate) -> Ticket:
        route = TICKET_ROUTES.get(data.category) or TICKET_ROUTES["default"]
        adapter = build_adapter(route)

        # Сначала заявка в тикет-системе (локальная запись появится только
        # после того, как получили внешний ключ — иначе он был бы null)
        req = TicketRequest(
            title=data.title,
            description=data.description,
        )
        created = await adapter.create(req)

        ticket = Ticket(
            title=data.title,
            description=data.description,
            category=data.category if data.category in TICKET_ROUTES else "default",
            author_name=data.author_name,
            system=route["system"],
            external_id=created.external_id,
            display_key=created.display_key,
            status="created",
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        return ticket


service = TicketService()
