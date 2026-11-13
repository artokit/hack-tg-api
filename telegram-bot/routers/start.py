from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from keyboards import start as start_keyboard
from services.user_service import user_service

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    user = await user_service.get_user_by_telegram_id(message.from_user.id)
    if user is None:
        await user_service.create_user(
            message.from_user.id, message.from_user.username
        )
    await message.answer(
        f"Здравствуйте! Вас приветствует чат-бот БАРС ГРУП СПАСИТЕ ПОМОГИТЕ.\n",
        reply_markup=start_keyboard.get_admin_start_keyboard(),
    )


@router.message(Command("me"))
async def cmd_me(message: Message):
    """Получает пользователя по id через GET /users/{id}.

    Использование: /me 1
    """
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Укажи id: /me <id>")
        return

    user = await user_service.get_user_by_id(int(args[1]))
    if user is None:
        await message.answer(f"Пользователь с id {args[1]} не найден")
        return

    await message.answer(
        f"id: {user.id}\n"
        f"telegram_user_id: {user.telegram_user_id}\n"
        f"username: {user.username or '—'}"
    )
