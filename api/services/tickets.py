from repositories.tickets import TicketRepository
from schemas.tickets import TicketCreate, TicketMessageCreate, TicketTake


class TicketService:
    def __init__(self, repository: TicketRepository):
        self._repository = repository

    async def create(self, data: TicketCreate):
        return await self._repository.create(data.user_id)

    async def get_by_group_id(self, group_id: str):
        return await self._repository.get_by_group_id(group_id)

    async def add_message(self, group_id: str, data: TicketMessageCreate):
        ticket = await self._repository.get_by_group_id(group_id)
        if ticket is None:
            raise LookupError("Ticket not found")
        return await self._repository.add_message(ticket.id, data.sender, data.text)

    async def get_messages(self, group_id: str) -> list:
        ticket = await self._repository.get_by_group_id(group_id)
        if ticket is None:
            raise LookupError("Ticket not found")
        return await self._repository.get_messages(ticket.id)

    async def take(self, group_id: str, data: TicketTake):
        ticket = await self._repository.get_by_group_id(group_id)
        if ticket is None:
            raise LookupError("Ticket not found")
        if ticket.status == "taken":
            raise ValueError("Ticket already taken")
        return await self._repository.take(ticket, data.taken_by_username)
