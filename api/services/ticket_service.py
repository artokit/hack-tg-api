import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import TICKET_ROUTES
from db.models import Ticket
from repositories.tickets import TicketRepository
from schemas.ticket import TicketCreate
from tickets.base import TicketRequest
from tickets.jsm import (
    TicketAttachmentRejected, TicketCreationDeferred, TicketCreationUncertain, TicketSystemError,
)
from tickets.registry import build_adapter


log = logging.getLogger(__name__)


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
        key = await adapter.create(req)

        ticket = Ticket(
            title=data.title,
            description=data.description,
            category=data.category if data.category in TICKET_ROUTES else "default",
            author_name=data.author_name,
            system=route["system"],
            status="created",
            external_key=key,
        )
        return await self._repository.create(ticket)

    async def process_support_ticket(self) -> bool:
        ticket = await self._repository.claim_support_ticket()
        if ticket is None:
            return False
        request_id = ticket.support_request_id
        assert request_id is not None
        reference = f"BARSREQ{request_id.hex}"
        route = TICKET_ROUTES.get(ticket.category) or TICKET_ROUTES["default"]
        adapter = build_adapter(route)
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)

        if ticket.status == "creating":
            try:
                ticket.external_key = await adapter.create(TicketRequest(
                    title=ticket.title, description=f"{ticket.description}\n\n{reference}",
                ))
                ticket.status = "attachment_pending"
                ticket.next_attempt_at = datetime.now(timezone.utc)
            except TicketCreationDeferred:
                ticket.status = "queued"
                ticket.next_attempt_at = retry_at
            except TicketCreationUncertain:
                log.warning("Jira creation outcome is uncertain for support request %s", request_id)
                ticket.status = "unknown"
                ticket.next_attempt_at = retry_at
            except TicketSystemError:
                log.warning("Jira rejected support request %s", request_id)
                ticket.status = "failed"
                ticket.next_attempt_at = None
        elif ticket.status == "unknown":
            try:
                ticket.external_key = await adapter.find_by_reference(reference)
                if ticket.external_key is not None:
                    ticket.status = "attachment_pending"
            except (TicketSystemError, httpx.HTTPError, ValueError, KeyError):
                log.warning("Jira reconciliation failed for support request %s", request_id)
            ticket.next_attempt_at = datetime.now(timezone.utc) if ticket.external_key else retry_at
        else:
            assert ticket.external_key is not None and ticket.conversation is not None
            try:
                await adapter.attach_internal(
                    ticket.external_key, f"conversation-{request_id}.txt", ticket.conversation.encode("utf-8"),
                )
                ticket.status = "created"
                ticket.conversation = None
                ticket.next_attempt_at = None
            except TicketAttachmentRejected:
                log.warning("Jira rejected the attachment for support request %s", request_id)
                ticket.status = "attachment_failed"
                ticket.next_attempt_at = None
            except (TicketSystemError, httpx.HTTPError, ValueError, KeyError, IndexError):
                log.warning("Jira attachment pending for support request %s", request_id)
                ticket.next_attempt_at = retry_at
        await self._repository.save()
        return True


async def run_support_tickets(sessions: async_sessionmaker[AsyncSession]) -> None:
    while True:
        try:
            async with sessions() as session:
                if await TicketService(TicketRepository(session)).process_support_ticket():
                    continue
        except Exception as error:
            log.warning("Support ticket worker failed (%s)", type(error).__name__)
        await asyncio.sleep(2)
