from pydantic_ai import Conversation, ConversationTypeAdapter
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversations import AgentConversation


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load(self, telegram_user_id: int) -> Conversation | None:
        row = await self.session.get(AgentConversation, telegram_user_id)
        if row is None:
            return None
        return ConversationTypeAdapter.validate_python(row.snapshot)

    async def save(self, telegram_user_id: int, conversation: Conversation) -> None:
        snapshot = ConversationTypeAdapter.dump_python(conversation, mode="json")
        statement = insert(AgentConversation).values(
            telegram_user_id=telegram_user_id, snapshot=snapshot
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[AgentConversation.telegram_user_id],
                set_={"snapshot": statement.excluded.snapshot},
            )
        )

    async def delete(self, telegram_user_id: int) -> None:
        await self.session.execute(
            delete(AgentConversation).where(
                AgentConversation.telegram_user_id == telegram_user_id
            )
        )
