from repositories.users import UserRepository
from schemas.users import UserCreate


class UserService:
    def __init__(self, repository: UserRepository):
        self._repository = repository

    async def create(self, data: UserCreate):
        existing = await self._repository.get_by_telegram_id(data.telegram_user_id)
        if existing is not None:
            raise ValueError("User with this telegram_user_id already exists")
        return await self._repository.create(data.telegram_user_id, data.username)

    async def get_by_id(self, user_id: int):
        return await self._repository.get(user_id)

    async def get_by_telegram_id(self, telegram_user_id: int):
        return await self._repository.get_by_telegram_id(telegram_user_id)
