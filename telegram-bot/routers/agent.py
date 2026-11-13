import logging

import httpx
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from services.agent_client import AgentClient, AgentStreamError
from services.live_chat import LiveChat

logger = logging.getLogger(__name__)
router = Router(name="agent")
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def send_error(
    message: Message, error: httpx.HTTPError | AgentStreamError
) -> None:
    if isinstance(error, AgentStreamError) and str(error) == "busy":
        await message.answer("Я ещё отвечаю на предыдущий вопрос. Попробуй чуть позже.")
        return
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 409:
            await message.answer(
                "Я ещё отвечаю на предыдущий вопрос. Попробуй чуть позже."
            )
            return
        if status == 422:
            await message.answer("Отправь текст длиной до 4096 символов.")
            return
    logger.warning("Agent API request failed (%s)", type(error).__name__)
    await message.answer("Сейчас не получается ответить. Попробуй ещё раз чуть позже.")


@router.message(Command("reset"))
async def reset(message: Message, agent_client: AgentClient) -> None:
    if message.from_user is None:
        return
    try:
        await agent_client.reset(message.from_user.id)
    except httpx.HTTPError as exc:
        await send_error(message, exc)
        return
    await message.answer("Диалог сброшен. Можешь написать новый вопрос.")


@router.message(F.text, ~F.text.startswith("/"))
async def chat(message: Message, live_chat: LiveChat) -> None:
    if message.from_user is None or message.text is None:
        return
    text = message.text.strip()
    if not text:
        return
    try:
        await live_chat.submit(message, message.from_user.id, text)
    except (httpx.HTTPError, AgentStreamError) as exc:
        await send_error(message, exc)
