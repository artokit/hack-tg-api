from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.users import User
from repositories.users import UserRepository


class UserService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def register(self, telegram_user_id: int, username: str | None) -> User:
        async with self.sessions.begin() as session:
            return await UserRepository(session).register(telegram_user_id, username)

    async def get(self, user_id: int) -> User | None:
        async with self.sessions() as session:
            return await UserRepository(session).get(user_id)
