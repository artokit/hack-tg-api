from repositories.employees import EmployeeRepository
from schemas.employees import EmployeeCreate


class EmployeeService:
    def __init__(self, repository: EmployeeRepository):
        self._repository = repository

    async def create(self, data: EmployeeCreate, username: str | None = None):
        existing = await self._repository.get_by_telegram_id(data.telegram_id)
        if existing is not None:
            raise ValueError("Employee already exists")
        return await self._repository.create(
            data.telegram_id, data.first_name, data.last_name, username
        )

    async def get_by_telegram_id(self, telegram_id: int):
        return await self._repository.get_by_telegram_id(telegram_id)

    async def get_all(self, page: int, page_size: int):
        items = await self._repository.get_all((page - 1) * page_size, page_size)
        total = await self._repository.count()
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
