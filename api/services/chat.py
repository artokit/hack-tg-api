import asyncio

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import UnexpectedModelBehavior
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from utils.unit_of_work import unit_of_work

TURN_TIMEOUT_SECONDS = 45


class ConversationBusy(Exception):
    pass


class ChatService:
    def __init__(
        self, agent: Agent[None, str], sessions: async_sessionmaker[AsyncSession]
    ) -> None:
        self.agent = agent
        self.sessions = sessions

    async def reply(self, telegram_user_id: int, text: str) -> str:
        async with (
            asyncio.timeout(TURN_TIMEOUT_SECONDS),
            unit_of_work(self.sessions) as work,
        ):
            if not await work.try_lock_conversation(telegram_user_id):
                raise ConversationBusy
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
        async with (
            asyncio.timeout(TURN_TIMEOUT_SECONDS),
            unit_of_work(self.sessions) as work,
        ):
            if not await work.try_lock_conversation(telegram_user_id):
                raise ConversationBusy
            await work.conversations.delete(telegram_user_id)
