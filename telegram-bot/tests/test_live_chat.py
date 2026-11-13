import asyncio
import json
from datetime import UTC, datetime

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.enums import ChatAction
from aiogram.types import Update

from routers import agent
from services.agent_client import AgentClient
from services.live_chat import LiveChat


def frame(kind: str, text: str = "") -> bytes:
    return f"event: {kind}\ndata: {json.dumps(text)}\n\n".encode()


def update(text: str, message_id: int) -> Update:
    return Update.model_validate(
        {
            "update_id": message_id,
            "message": {
                "message_id": message_id,
                "date": datetime.now(UTC),
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 123, "is_bot": False, "first_name": "Demo"},
                "text": text,
            },
        }
    )


def test_telegram_steers_a_running_reply_and_formats_one_final_answer() -> None:
    async def scenario() -> None:
        typing_ready = asyncio.Event()
        steer_received = asyncio.Event()
        paths: list[str] = []
        answers: list[str] = []
        turn_id: str | None = None

        class CaptureSession(BaseSession):
            async def close(self) -> None:
                pass

            async def make_request(self, bot, method, timeout=None):
                match method.__api_method__:
                    case "sendChatAction":
                        assert method.action == ChatAction.TYPING
                        typing_ready.set()
                    case "sendRichMessage":
                        answers.append(method.rich_message.markdown)
                    case _:
                        raise AssertionError(method.__api_method__)
                return True

            async def stream_content(self, *args, **kwargs):
                if False:
                    yield b""

        class AgentEvents(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield frame("ready")
                await steer_received.wait()
                yield frame("answer", "**Итог с уточнением**")

        def handle(request: httpx.Request) -> httpx.Response:
            nonlocal turn_id
            assert request.headers["Authorization"] == "Bearer test"
            paths.append(request.url.path)
            data = json.loads(request.content)
            if request.url.path == "/agent/chat/stream":
                turn_id = data["turn_id"]
                return httpx.Response(200, stream=AgentEvents())
            assert request.url.path == "/agent/chat/steer"
            assert data["turn_id"] == turn_id
            assert data["text"] == "Только три пункта"
            steer_received.set()
            return httpx.Response(202)

        dispatcher = Dispatcher()
        dispatcher.include_router(agent.router)
        async with (
            Bot("123456:test", session=CaptureSession()).context() as bot,
            httpx.AsyncClient(
                base_url="http://test/", transport=httpx.MockTransport(handle)
            ) as http,
            asyncio.TaskGroup() as tasks,
        ):
            chat = LiveChat(AgentClient(http, "test"))
            first = tasks.create_task(
                dispatcher.feed_update(bot, update("Как оформить?", 1), live_chat=chat)
            )
            await asyncio.wait_for(typing_ready.wait(), timeout=3)
            assert not answers
            await asyncio.wait_for(
                dispatcher.feed_update(
                    bot, update("Только три пункта", 2), live_chat=chat
                ),
                timeout=3,
            )
            await asyncio.wait_for(first, timeout=3)

        assert paths == ["/agent/chat/stream", "/agent/chat/steer"]
        assert answers == ["**Итог с уточнением**"]
        assert not chat.active

    asyncio.run(scenario())
