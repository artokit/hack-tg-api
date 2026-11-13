import asyncio
import logging
from collections.abc import Iterator
from contextlib import suppress

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
        self.text = ""
        self.last_draft = ""
        self.next_draft_at = 0.0
        self.drafts_enabled = True
        self.waiting_for_text = True

    async def typing(self) -> None:
        while True:
            if self.waiting_for_text or not self.drafts_enabled:
                try:
                    await self.message.bot.send_chat_action(
                        self.message.chat.id, ChatAction.TYPING, request_timeout=4
                    )
                except TelegramAPIError as exc:
                    logger.debug("Typing failed (%s)", type(exc).__name__)
            await asyncio.sleep(4)

    async def draft(self, text: str) -> None:
        self.text += text
        now = asyncio.get_running_loop().time()
        if not self.drafts_enabled or now < self.next_draft_at:
            return
        preview = next(split_reply(self.text), "")
        if not preview.strip() or preview == self.last_draft:
            return
        self.next_draft_at = now + 1
        try:
            await self.message.bot.send_message_draft(
                chat_id=self.message.chat.id,
                draft_id=self.message.message_id,
                text=preview,
                request_timeout=3,
            )
        except TelegramRetryAfter as exc:
            self.next_draft_at = now + exc.retry_after
        except TelegramAPIError as exc:
            self.drafts_enabled = False
            logger.debug("Draft unavailable (%s)", type(exc).__name__)
        else:
            self.last_draft = preview
            self.waiting_for_text = False

    def restart_draft(self) -> None:
        self.text = ""
        self.waiting_for_text = True

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

    async def clear_draft(self) -> None:
        if self.last_draft and self.drafts_enabled:
            with suppress(TelegramAPIError):
                await self.message.bot.send_message_draft(
                    chat_id=self.message.chat.id,
                    draft_id=self.message.message_id,
                    text="",
                    request_timeout=3,
                )
