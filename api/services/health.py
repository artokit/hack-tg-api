from repositories.health import HealthRepository


class HealthService:
    def __init__(self, repository: HealthRepository):
        self._repository = repository

    async def is_available(self) -> bool:
        return await self._repository.is_available()
