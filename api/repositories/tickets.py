from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SupportRequest, Ticket


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def by_support_request(self, request_id: UUID) -> Ticket | None:
        return await self._session.scalar(
            select(Ticket).where(Ticket.support_request_id == request_id)
        )

    async def jira_recipient(self, external_key: str, external_id: str) -> SupportRequest | None:
        return (await self._session.scalars(
            select(SupportRequest)
            .join(Ticket, Ticket.support_request_id == SupportRequest.id)
            .where(
                Ticket.system == "jsm",
                Ticket.external_key == external_key,
                Ticket.external_id == external_id,
            )
            .limit(2)
        )).one_or_none()

    async def get_for_update(self, ticket_id: int) -> Ticket | None:
        return await self._session.get(Ticket, ticket_id, with_for_update=True)

    async def create(self, ticket: Ticket) -> Ticket:
        self._session.add(ticket)
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(ticket)
        return ticket

    async def claim_support_ticket(self) -> Ticket | None:
        now = datetime.now(timezone.utc)
        async with self._session.begin():
            ticket = await self._session.scalar(
                select(Ticket)
                .where(
                    Ticket.support_request_id.is_not(None),
                    Ticket.next_attempt_at <= now,
                    Ticket.status.in_(("queued", "creating", "unknown")),
                )
                .order_by(Ticket.next_attempt_at, Ticket.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if ticket is not None:
                if ticket.status == "creating":
                    ticket.status = "unknown"
                elif ticket.status == "queued":
                    ticket.status = "creating"
                ticket.next_attempt_at = now + timedelta(minutes=5)
        return ticket

    async def save(self) -> None:
        await self._session.commit()
