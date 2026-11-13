from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_operator_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перевести на оператора", callback_data="to_operator")]
        ]
    )

    return keyboard
