from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.users import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register(self, telegram_user_id: int, username: str | None) -> User:
        statement = (
            insert(User)
            .values(telegram_user_id=telegram_user_id, username=username)
            .on_conflict_do_nothing(index_elements=[User.telegram_user_id])
            .returning(User)
        )
        created = await self.session.scalar(statement)
        if created is not None:
            return created
        existing = await self.session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        return existing.scalar_one()

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)
