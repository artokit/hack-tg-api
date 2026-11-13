from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import BigInteger, bindparam, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repositories.conversations import ConversationRepository
from repositories.users import UserRepository


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversations = ConversationRepository(session)
        self.users = UserRepository(session)

    async def try_lock_conversation(self, telegram_user_id: int) -> bool:
        statement = select(
            func.pg_try_advisory_xact_lock(bindparam("chat_id", type_=BigInteger))
        )
        return bool(await self.session.scalar(statement, {"chat_id": telegram_user_id}))


@asynccontextmanager
async def unit_of_work(
    sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[UnitOfWork]:
    async with sessions.begin() as session:
        yield UnitOfWork(session)
