import asyncio
import logging
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import httpx
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
        typing = asyncio.create_task(display.typing())
        try:
            await self._reply(display, user_id, text, turn)
        finally:
            typing.cancel()
            turn.accepting = False
            del self.active[user_id]
            turn.ready.set()
            turn.done.set()
            with suppress(asyncio.CancelledError):
                await typing

    async def _reply(
        self, display: ReplyDisplay, user_id: int, text: str, turn: ActiveReply
    ) -> None:
        try:
            async with aclosing(
                self.client.stream(user_id, turn.turn_id, text)
            ) as events:
                async for kind, content in events:
                    match kind:
                        case "ready":
                            turn.accepting = True
                            turn.ready.set()
                        case "text":
                            await display.draft(content)
                        case "draft_reset":
                            display.restart_draft()
                        case "answer":
                            turn.accepting = False
                            await display.answer(content)
                            return
                        case "error":
                            raise AgentStreamError(content)
            raise AgentStreamError("missing final answer")
        except (AgentStreamError, httpx.HTTPError):
            await display.clear_draft()
            raise
        except TelegramAPIError as exc:
            logger.warning("Telegram reply delivery failed (%s)", type(exc).__name__)
            await display.clear_draft()
