from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.users import User
from utils.unit_of_work import unit_of_work


class UserService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def register(self, telegram_user_id: int, username: str | None) -> User:
        async with unit_of_work(self.sessions) as work:
            return await work.users.register(telegram_user_id, username)

    async def get(self, user_id: int) -> User | None:
        async with unit_of_work(self.sessions) as work:
            return await work.users.get(user_id)
