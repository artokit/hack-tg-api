from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Ticket, TicketMessage


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_group_id(self, group_id: str) -> Ticket | None:
        return await self._session.scalar(
            select(Ticket).where(Ticket.group_id == group_id)
        )

    async def create(self, user_id: int) -> Ticket:
        ticket = Ticket(user_id=user_id)
        self._session.add(ticket)
        await self._session.commit()
        await self._session.refresh(ticket)
        return ticket

    async def add_message(self, ticket_id: int, sender: str, text: str) -> TicketMessage:
        message = TicketMessage(ticket_id=ticket_id, sender=sender, text=text)
        self._session.add(message)
        await self._session.commit()
        await self._session.refresh(message)
        return message

    async def get_messages(self, ticket_id: int) -> list[TicketMessage]:
        result = await self._session.scalars(
            select(TicketMessage)
            .where(TicketMessage.ticket_id == ticket_id)
            .order_by(TicketMessage.id)
        )
        return list(result)

    async def take(self, ticket: Ticket, taken_by_username: str) -> Ticket:
        ticket.status = "taken"
        ticket.taken_by_username = taken_by_username
        await self._session.commit()
        await self._session.refresh(ticket)
        return ticket
