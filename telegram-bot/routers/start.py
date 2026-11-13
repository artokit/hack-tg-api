import logging

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, api_client: httpx.AsyncClient) -> None:
    if message.from_user is None:
        return
    try:
        response = await api_client.post(
            "users",
            json={
                "telegram_user_id": message.from_user.id,
                "username": message.from_user.username,
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Registration failed (%s)", type(exc).__name__)
        await message.answer(
            "Сейчас не получается зарегистрироваться. Попробуй чуть позже."
        )
        return
    await message.answer(
        f"Привет, {message.from_user.full_name}!\n"
        "Напиши свой вопрос. Чтобы начать новый диалог, отправь /reset."
    )


@router.message(Command("me"))
async def cmd_me(message: Message, api_client: httpx.AsyncClient) -> None:
    args = (message.text or "").split()
    if (
        len(args) < 2
        or not args[1].isascii()
        or not args[1].isdigit()
        or len(args[1]) > 10
    ):
        await message.answer("Укажи id: /me <id>")
        return
    user_id = int(args[1])
    try:
        response = await api_client.get(f"users/{user_id}")
        if response.status_code == 404:
            await message.answer(f"Пользователь с id {user_id} не найден")
            return
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("User lookup failed (%s)", type(exc).__name__)
        await message.answer(
            "Сейчас не получается получить пользователя. Попробуй чуть позже."
        )
        return
    user = response.json()
    username = user.get("username") or "—"
    await message.answer(
        f"id: {user['id']}\n"
        f"telegram_user_id: {user['telegram_user_id']}\n"
        f"username: {username}"
    )
