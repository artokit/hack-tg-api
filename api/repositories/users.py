from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        return await self._session.scalar(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )

    async def get(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def create(self, telegram_user_id: int, username: str | None) -> User:
        user = User(telegram_user_id=telegram_user_id, username=username)
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user
