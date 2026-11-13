from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_start_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Задать вопрос", callback_data="ask")]
        ]
    )

    return keyboard