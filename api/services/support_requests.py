import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from config import TICKET_ROUTES
from db.models import SupportRequest, Ticket
from repositories.support_requests import SupportRequestRepository
from repositories.tickets import TicketRepository
from schemas.support_requests import RequestCostRead, SupportRequestCreate
from schemas.ticket import TicketCreate
from tickets.jsm import TicketSystemError
from tickets.registry import build_adapter


log = logging.getLogger(__name__)


class SupportRequestConflict(Exception):
    pass


class SupportRequestNotFound(Exception):
    pass


class SupportRequestService:
    def __init__(self, requests: SupportRequestRepository, tickets: TicketRepository):
        self._requests = requests
        self._tickets = tickets

    async def get(self, request_id: UUID) -> SupportRequest:
        request = await self._requests.get(request_id)
        if request is None:
            raise SupportRequestNotFound
        return request

    async def record_kb_search(self, instance_id: str | None) -> None:
        if instance_id is not None:
            await self._requests.record_kb_search(instance_id)

    async def cost_summary(self, from_at: datetime | None, to_at: datetime | None) -> RequestCostRead:
        closed_count, priced_count, total = await self._requests.cost_summary(from_at, to_at)
        return RequestCostRead(
            closed_count=closed_count, priced_count=priced_count,
            total=float(total) if total is not None else None,
            mean=float(total / priced_count) if total is not None else None,
        )

    async def create(self, data: SupportRequestCreate) -> SupportRequest:
        try:
            return await self._requests.create(SupportRequest(**data.model_dump()))
        except IntegrityError as error:
            raise SupportRequestConflict from error

    async def get_ticket(self, request_id: UUID) -> Ticket:
        ticket = await self._tickets.by_support_request(request_id)
        if ticket is None:
            raise SupportRequestNotFound
        if ticket.status == "created" and ticket.external_id and ticket.external_url is None:
            adapter = build_adapter(TICKET_ROUTES.get(ticket.category) or TICKET_ROUTES["default"])
            try:
                ticket.external_url = await adapter.get_ticket_url(ticket.external_id)
            except TicketSystemError:
                log.warning("Could not retrieve Jira URL for support request %s", request_id)
            else:
                await self._tickets.save()
        return ticket

    async def create_ticket(self, request_id: UUID, data: TicketCreate) -> Ticket:
        request = await self.get(request_id)
        if request.close_reason not in {"rag_exhausted", "operator_requested"}:
            raise SupportRequestConflict
        ticket = Ticket(
            title=data.title,
            description=data.description,
            category="default",
            system=TICKET_ROUTES["default"]["system"],
            status="queued",
            support_request_id=request.id,
            next_attempt_at=datetime.now(timezone.utc),
        )
        try:
            return await self._tickets.create(ticket)
        except IntegrityError as error:
            raise SupportRequestConflict from error
