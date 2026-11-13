import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress

from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InputRichMessage, Message

logger = logging.getLogger(__name__)


def split_reply(text: str) -> Iterator[str]:
    # Stay within Telegram's limit with UTF-16 surrogate pairs intact.
    encoded = text.encode("utf-16-le")
    limit = 4096 * 2
    start = 0
    while start < len(encoded):
        end = min(start + limit, len(encoded))
        if end < len(encoded) and 0xD8 <= encoded[end - 1] <= 0xDB:
            end -= 2
        yield encoded[start:end].decode("utf-16-le")
        start = end


class ReplyDisplay:
    def __init__(self, message: Message) -> None:
        self.message = message

    @asynccontextmanager
    async def typing(self) -> AsyncIterator[None]:
        task = asyncio.create_task(self._keep_typing())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _keep_typing(self) -> None:
        while True:
            try:
                await self.message.bot.send_chat_action(
                    self.message.chat.id, ChatAction.TYPING, request_timeout=4
                )
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                continue
            except TelegramAPIError as exc:
                logger.debug("Typing failed (%s)", type(exc).__name__)
            await asyncio.sleep(4)

    async def answer(self, text: str) -> None:
        try:
            await self._send_rich(text)
        except TelegramBadRequest:
            for part in split_reply(text):
                try:
                    await self.message.answer(part)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after)
                    await self.message.answer(part)

    async def _send_rich(self, text: str) -> None:
        rich_message = InputRichMessage(markdown=text)
        bot = self.message.bot
        chat_id = self.message.chat.id
        try:
            await bot.send_rich_message(chat_id=chat_id, rich_message=rich_message)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            await bot.send_rich_message(chat_id=chat_id, rich_message=rich_message)
