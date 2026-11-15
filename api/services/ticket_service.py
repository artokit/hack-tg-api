import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import TICKET_ROUTES
from db.models import Ticket
from repositories.tickets import TicketRepository
from schemas.ticket import TicketCreate
from tickets.base import TicketAttachment, TicketRequest, TicketSystem
from tickets.jsm import TicketCreationDeferred, TicketCreationUncertain, TicketSystemError
from tickets.registry import build_adapter


log = logging.getLogger(__name__)


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

    async def process_support_ticket(self) -> bool:
        ticket = await self._repository.claim_support_ticket()
        if ticket is None:
            return False
        request_id = ticket.support_request_id
        assert request_id is not None
        reference = f"BARSREQ{request_id.hex}"
        adapter = build_adapter(TICKET_ROUTES.get(ticket.category) or TICKET_ROUTES["default"])
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)

        if ticket.status == "creating":
            try:
                created = await adapter.create(TicketRequest(
                    title=ticket.title, description=f"{ticket.description}\n\n{reference}",
                ))
            except TicketCreationDeferred:
                ticket.status = "queued"
                ticket.next_attempt_at = retry_at
                created = None
            except TicketCreationUncertain:
                log.warning("Jira creation outcome is uncertain for support request %s", request_id)
                ticket.status = "unknown"
                ticket.next_attempt_at = retry_at
                created = None
            except TicketSystemError:
                log.warning("Jira rejected support request %s", request_id)
                ticket.status = "failed"
                ticket.next_attempt_at = None
                created = None
        else:
            ticket.next_attempt_at = retry_at
            try:
                created = await adapter.find_by_reference(reference)
            except (TicketSystemError, httpx.HTTPError, ValueError, KeyError, TypeError):
                log.warning("Jira reconciliation failed for support request %s", request_id)
                created = None
        if created is not None:
            ticket.external_key = created.external_key
            ticket.external_id = created.external_id
            ticket.status = "created"
            ticket.next_attempt_at = None
        await self._repository.save()
        return True


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
        ticket = await self._repository.get_for_update(ticket_id)
        if ticket is None:
            raise TicketLookupError("Заявка не найдена", 404)
        if not ticket.external_key:
            raise TicketLookupError("У заявки нет привязки к тикет-системе", 400)
        is_transcript = (
            ticket.support_request_id is not None
            and filename == f"conversation-{ticket.support_request_id}.txt"
            and not public
        )
        if is_transcript and ticket.attachment_comment_id:
            return TicketAttachment(ticket.external_key, ticket.attachment_comment_id, filename, public)
        if is_transcript and await self._system.has_attachment(ticket.external_key, filename):
            raise TicketLookupError("Переписка уже прикреплена", 409)
        attachment = await self._system.attach_file(
            ticket.external_key, filename, content, content_type, public
        )
        if is_transcript:
            ticket.attachment_comment_id = attachment.comment_id
            await self._repository.save()
        return attachment


async def run_support_tickets(sessions: async_sessionmaker[AsyncSession]) -> None:
    while True:
        try:
            async with sessions() as session:
                if await TicketService(TicketRepository(session)).process_support_ticket():
                    continue
        except Exception as error:
            log.warning("Support ticket worker failed (%s)", type(error).__name__)
        await asyncio.sleep(2)
