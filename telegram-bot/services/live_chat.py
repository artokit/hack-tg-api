import asyncio
import logging
from contextlib import aclosing
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from services.agent_client import AgentClient, AgentStreamError
from services.reply_display import ReplyDisplay

logger = logging.getLogger(__name__)


@dataclass
class ActiveReply:
    turn_id: UUID = field(default_factory=uuid4)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    steering: asyncio.Lock = field(default_factory=asyncio.Lock)
    accepting: bool = False


class LiveChat:
    def __init__(self, client: AgentClient) -> None:
        self.client = client
        self.active: dict[int, ActiveReply] = {}

    async def submit(self, message: Message, user_id: int, text: str) -> None:
        while (turn := self.active.get(user_id)) is not None:
            await turn.ready.wait()
            async with turn.steering:
                if turn.accepting and await self.client.steer(
                    user_id, turn.turn_id, text
                ):
                    return
            await turn.done.wait()

        turn = ActiveReply()
        self.active[user_id] = turn
        display = ReplyDisplay(message)
        try:
            async with display.typing():
                answer = await self._answer(user_id, text, turn)
            await display.answer(answer)
        except TelegramAPIError as exc:
            logger.warning("Telegram reply delivery failed (%s)", type(exc).__name__)
        finally:
            turn.accepting = False
            del self.active[user_id]
            turn.ready.set()
            turn.done.set()

    async def _answer(self, user_id: int, text: str, turn: ActiveReply) -> str:
        async with aclosing(self.client.stream(user_id, turn.turn_id, text)) as events:
            async for kind, content in events:
                match kind:
                    case "ready":
                        turn.accepting = True
                        turn.ready.set()
                    case "answer":
                        turn.accepting = False
                        return content
                    case "error":
                        raise AgentStreamError(content)
        raise AgentStreamError("missing final answer")
