import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic_ai import RunContext, UsageLimits
from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError

from services.chat import ChatService

LIVE_TURN_TIMEOUT_SECONDS = 90


class TurnClosed(Exception):
    pass


@dataclass(frozen=True)
class TurnEvent:
    kind: Literal["ready", "answer"]
    text: str = ""


@dataclass
class ActiveTurn:
    turn_id: UUID
    context: RunContext[None] | None = None
    pending: list[str] = field(default_factory=list)

    def bind(self, context: RunContext[None]) -> None:
        self.context = context
        for text in self.pending:
            context.enqueue(text, priority="asap")
        self.pending.clear()

    def steer(self, text: str) -> None:
        if self.context is None:
            self.pending.append(text)
            return
        try:
            self.context.enqueue(text, priority="asap")
        except UserError:
            raise TurnClosed from None


class LiveTurns:
    def __init__(self, chat: ChatService) -> None:
        self.chat = chat
        self.active: dict[int, ActiveTurn] = {}

    def steer(self, user_id: int, turn_id: UUID, text: str) -> None:
        turn = self.active.get(user_id)
        if turn is None or turn.turn_id != turn_id:
            raise TurnClosed
        turn.steer(text)

    async def stream(
        self, user_id: int, turn_id: UUID, text: str
    ) -> AsyncIterator[TurnEvent]:
        events: asyncio.Queue[TurnEvent | Exception | None] = asyncio.Queue()

        async def produce() -> None:
            try:
                await self._run(user_id, turn_id, text, events)
            except Exception as exc:  # noqa: BLE001 - relay failures to the stream consumer
                await events.put(exc)
            else:
                await events.put(None)

        run = asyncio.create_task(produce())
        try:
            while (event := await events.get()) is not None:
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            run.cancel()
            with suppress(asyncio.CancelledError):
                await run

    async def _run(
        self,
        user_id: int,
        turn_id: UUID,
        text: str,
        events: asyncio.Queue[TurnEvent | Exception | None],
    ) -> None:
        async with self.chat.locked_conversation(
            user_id, timeout=LIVE_TURN_TIMEOUT_SECONDS
        ) as work:
            turn = ActiveTurn(turn_id)
            self.active[user_id] = turn
            try:
                events.put_nowait(TurnEvent("ready"))
                conversation = await work.conversations.load(user_id)
                result = await self.chat.agent.run(
                    text,
                    conversation=conversation,
                    capabilities=[Hooks(before_run=turn.bind)],
                    usage_limits=UsageLimits(request_limit=None),
                )
                answer = result.output.strip()
                if not answer:
                    raise UnexpectedModelBehavior(
                        "The chat model returned an empty answer"
                    )
                await work.conversations.save(user_id, result.conversation)
            finally:
                del self.active[user_id]
        events.put_nowait(TurnEvent("answer", answer))
