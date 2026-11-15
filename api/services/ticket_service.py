from config import TICKET_ROUTES
from db.models import Ticket
from repositories.tickets import TicketRepository
from schemas.ticket import TicketCreate
from tickets.base import TicketAttachment, TicketRequest, TicketSystem
from tickets.registry import build_adapter


class TicketLookupError(Exception):
    def __init__(self, message: str, status_code: int = 404):
        super().__init__(message)
        self.status_code = status_code


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
        created = await adapter.create(req)

        ticket = Ticket(
            title=data.title,
            description=data.description,
            category=data.category if data.category in TICKET_ROUTES else "default",
            author_name=data.author_name,
            system=route["system"],
            status="created",
            external_id=created.external_id,
            external_key=created.external_key,
        )
        return await self._repository.create(ticket)


class TicketAttachmentService:
    def __init__(self, repository: TicketRepository, system: TicketSystem):
        self._repository = repository
        self._system = system

    async def attach_file(
        self,
        ticket_id: int,
        filename: str,
        content: bytes,
        content_type: str,
        public: bool,
    ) -> TicketAttachment:
        ticket = await self._repository.get(ticket_id)
        if ticket is None:
            raise TicketLookupError("Заявка не найдена", 404)
        if not ticket.external_key:
            raise TicketLookupError("У заявки нет привязки к тикет-системе", 400)
        return await self._system.attach_file(
            ticket.external_key, filename, content, content_type, public
        )
