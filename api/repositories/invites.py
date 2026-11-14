from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Employee, Invite
from repositories.employees import EmployeeRepository


class InviteRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, invite_id: UUID) -> Invite | None:
        return await self._session.get(Invite, invite_id)

    async def get_all(self, offset: int, limit: int) -> list[Invite]:
        result = await self._session.scalars(
            select(Invite).order_by(Invite.id).offset(offset).limit(limit)
        )
        return list(result)

    async def count(self) -> int:
        return await self._session.scalar(select(func.count()).select_from(Invite))

    async def create(
        self, count_of_use: int, first_name: str | None, last_name: str | None
    ) -> Invite:
        invite = Invite(
            count_of_use=count_of_use, first_name=first_name, last_name=last_name
        )
        self._session.add(invite)
        await self._session.commit()
        await self._session.refresh(invite)
        return invite

    async def delete(self, invite: Invite) -> None:
        await self._session.delete(invite)
        await self._session.commit()

    async def lock_for_accept(self, invite_id: UUID) -> Invite | None:
        return await self._session.scalar(
            select(Invite).where(Invite.id == invite_id).with_for_update()
        )

    async def accept(
        self,
        invite: Invite,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> Employee:
        employees = EmployeeRepository(self._session)
        employee = employees.add(telegram_id, first_name, last_name, username)
        if invite.count_of_use == 1:
            await self._session.delete(invite)
        else:
            invite.count_of_use -= 1
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            if await employees.get_by_telegram_id(telegram_id) is not None:
                raise ValueError("Employee already exists") from error
            raise
        await self._session.refresh(employee)
        return employee
