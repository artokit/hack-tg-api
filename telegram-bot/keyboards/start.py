from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_start_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Посмотреть все департаменты", callback_data="list_departments")],
            [InlineKeyboardButton(text="Создать новый департамент", callback_data="create_department")],
        ]
    )

    return keyboard