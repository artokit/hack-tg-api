import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import UnexpectedModelBehavior
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from utils.unit_of_work import UnitOfWork, unit_of_work

TURN_TIMEOUT_SECONDS = 45


class ConversationBusy(Exception):
    pass


class ChatService:
    def __init__(
        self, agent: Agent[None, str], sessions: async_sessionmaker[AsyncSession]
    ) -> None:
        self.agent = agent
        self.sessions = sessions

    @asynccontextmanager
    async def locked_conversation(
        self, telegram_user_id: int, *, timeout: float = TURN_TIMEOUT_SECONDS
    ) -> AsyncIterator[UnitOfWork]:
        async with (
            asyncio.timeout(timeout),
            unit_of_work(self.sessions) as work,
        ):
            if not await work.try_lock_conversation(telegram_user_id):
                raise ConversationBusy
            yield work

    async def reply(self, telegram_user_id: int, text: str) -> str:
        async with self.locked_conversation(telegram_user_id) as work:
            conversation = await work.conversations.load(telegram_user_id)
            result = await self.agent.run(
                text,
                conversation=conversation,
                usage_limits=UsageLimits(request_limit=None),
            )
            answer = result.output.strip()
            if not answer:
                raise UnexpectedModelBehavior("The chat model returned an empty answer")
            await work.conversations.save(telegram_user_id, result.conversation)
        return answer

    async def reset(self, telegram_user_id: int) -> None:
        async with self.locked_conversation(telegram_user_id) as work:
            await work.conversations.delete(telegram_user_id)
