from config import TICKET_ROUTES
from db.models import Ticket
from repositories.tickets import TicketRepository
from schemas.ticket import TicketCreate
from tickets.base import TicketRequest
from tickets.registry import build_adapter


class TicketService:
    def __init__(self, repository: TicketRepository):
        self._repository = repository

    async def create(self, data: TicketCreate) -> Ticket:
        route = TICKET_ROUTES.get(data.category) or TICKET_ROUTES["default"]
        adapter = build_adapter(route)

        req = TicketRequest(
            title=data.title,
            description=data.description,
        )
        await adapter.create(req)

        ticket = Ticket(
            title=data.title,
            description=data.description,
            category=data.category if data.category in TICKET_ROUTES else "default",
            author_name=data.author_name,
            system=route["system"],
            status="created",
        )
        return await self._repository.create(ticket)
