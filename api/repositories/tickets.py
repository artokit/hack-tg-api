from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Ticket


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, ticket_id: int) -> Ticket | None:
        ticket = await self._session.get(Ticket, ticket_id)
        return ticket

    async def create(self, ticket: Ticket) -> Ticket:
        self._session.add(ticket)
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(ticket)
        return ticket
