import os

import httpx
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

API_URL = os.getenv("API_URL", "http://localhost:8000")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_URL}/users",
            json={
                "telegram_user_id": message.from_user.id,
                "username": message.from_user.username,
            },
        )
        resp.raise_for_status()
        user = resp.json()

    await message.answer(
        f"Привет, {message.from_user.full_name}!\n"
        f"Ты сохранён в базе, твой id: {user['id']}"
    )


@dp.message(Command("me"))
async def cmd_me(message: Message):
    """Получает пользователя по id через GET /users/{id}.

    Использование: /me 1
    """
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Укажи id: /me <id>")
        return

    user_id = int(args[1])
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_URL}/users/{user_id}")
        if resp.status_code == 404:
            await message.answer(f"Пользователь с id {user_id} не найден")
            return
        resp.raise_for_status()
        user = resp.json()

    username = user.get("username") or "—"
    await message.answer(
        f"id: {user['id']}\n"
        f"telegram_user_id: {user['telegram_user_id']}\n"
        f"username: {username}"
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
