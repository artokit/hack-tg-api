from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Employee


class EmployeeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, employee_id: UUID) -> Employee | None:
        return await self._session.get(Employee, employee_id)

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

    async def delete(self, employee: Employee) -> None:
        await self._session.delete(employee)
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def update_from_telegram(
        self,
        employee: Employee,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> Employee:
        employee.username = username
        employee.first_name = first_name
        employee.last_name = last_name
        employee.is_parsed = True
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(employee)
        return employee

    async def create(
        self,
        telegram_id: int,
        first_name: str | None,
        last_name: str | None,
        username: str | None = None,
    ) -> Employee:
        employee = self.add(telegram_id, first_name, last_name, username)
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            if await self.get_by_telegram_id(telegram_id) is not None:
                raise ValueError("Employee already exists") from error
            raise
        await self._session.refresh(employee)
        return employee

    def add(
        self,
        telegram_id: int,
        first_name: str | None,
        last_name: str | None,
        username: str | None,
        is_parsed: bool = False,
    ) -> Employee:
        employee = Employee(
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            is_parsed=is_parsed,
        )
        self._session.add(employee)
        return employee
