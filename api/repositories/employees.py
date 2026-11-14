from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Employee


class EmployeeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Employee | None:
        return await self._session.scalar(
            select(Employee).where(Employee.telegram_id == telegram_id)
        )

    async def get_all(self, offset: int, limit: int) -> list[Employee]:
        result = await self._session.scalars(
            select(Employee)
            .order_by(Employee.created_at, Employee.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result)

    async def count(self) -> int:
        return await self._session.scalar(select(func.count()).select_from(Employee))

    async def create(
        self,
        telegram_id: int,
        first_name: str | None,
        last_name: str | None,
    ) -> Employee:
        employee = Employee(
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
        )
        self._session.add(employee)
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            if await self.get_by_telegram_id(telegram_id) is not None:
                raise ValueError("Employee already exists") from error
            raise
        await self._session.refresh(employee)
        return employee
