from uuid import UUID

from pydantic import ValidationError

from repositories.employee_cache import EmployeeCacheRepository
from repositories.employees import EmployeeRepository
from schemas.employees import EmployeeCreate, EmployeeRead


class EmployeeService:
    def __init__(
        self, repository: EmployeeRepository, cache: EmployeeCacheRepository
    ):
        self._repository = repository
        self._cache = cache

    async def create(self, data: EmployeeCreate, username: str | None = None):
        existing = await self._repository.get_by_telegram_id(data.telegram_id)
        if existing is not None:
            raise ValueError("Employee already exists")
        return await self._repository.create(
            data.telegram_id, data.first_name, data.last_name, username
        )

    async def get_by_telegram_id(self, telegram_id: int):
        cached = await self._get_cached(telegram_id)
        if cached is not None:
            return cached
        async with self._cache.lock(telegram_id):
            cached = await self._get_cached(telegram_id)
            if cached is not None:
                return cached
            employee = await self._repository.get_by_telegram_id(telegram_id)
            if employee is not None:
                data = EmployeeRead.model_validate(employee)
                await self._cache.set(telegram_id, data.model_dump_json())
            return employee

    async def _get_cached(self, telegram_id: int) -> EmployeeRead | None:
        cached = await self._cache.get(telegram_id)
        if cached is None:
            return None
        try:
            employee = EmployeeRead.model_validate_json(cached)
        except ValidationError:
            await self._cache.delete(telegram_id)
            return None
        if employee.telegram_id != telegram_id:
            await self._cache.delete(telegram_id)
            return None
        return employee

    async def delete(self, employee_id: UUID) -> None:
        employee = await self._repository.get_by_id(employee_id)
        if employee is None:
            raise LookupError("Employee not found")
        async with self._cache.lock(employee.telegram_id):
            await self._cache.delete(employee.telegram_id)
            await self._repository.delete(employee)

    async def get_all(self, page: int, page_size: int):
        items = await self._repository.get_all((page - 1) * page_size, page_size)
        total = await self._repository.count()
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
