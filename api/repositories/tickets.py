from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Ticket


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, ticket: Ticket) -> Ticket:
        self._session.add(ticket)
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(ticket)
        return ticket
