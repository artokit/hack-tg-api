import logging
from collections.abc import Iterator

import httpx
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from services.agent_client import AgentClient

logger = logging.getLogger(__name__)
router = Router(name="agent")
router.message.filter(F.chat.type == ChatType.PRIVATE)


def split_reply(text: str) -> Iterator[str]:
    # Use UTF-16 code units, which also accounts for emoji outside the BMP.
    encoded = text.encode("utf-16-le")
    limit = 4096 * 2
    start = 0
    while start < len(encoded):
        end = min(start + limit, len(encoded))
        if end < len(encoded) and 0xD8 <= encoded[end - 1] <= 0xDB:
            end -= 2
        yield encoded[start:end].decode("utf-16-le")
        start = end


async def send_error(message: Message, error: httpx.HTTPError) -> None:
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
async def chat(message: Message, agent_client: AgentClient) -> None:
    if message.from_user is None or message.text is None:
        return
    text = message.text.strip()
    if not text:
        return
    try:
        answer = await agent_client.reply(message.from_user.id, text)
    except httpx.HTTPError as exc:
        await send_error(message, exc)
        return
    for part in split_reply(answer):
        await message.answer(part)
