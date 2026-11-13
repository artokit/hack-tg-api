from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from keyboards import ask as ask_keyboard
from states.ask import AskStates
from aiogram import Router, F

router = Router()


@router.callback_query(F.data == "ask")
async def ask(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Задайте свой вопрос")
    await state.set_state(AskStates.user_ask)


@router.message(AskStates.user_ask)
async def user_ask(message: Message, state: FSMContext):
    await message.answer(
        "Извините, я не знаю ответ на этот вопрос. Перевести на оператора ?",
        reply_markup=ask_keyboard.get_operator_keyboard(),
    )


@router.message(F.data == 'to_operator')
async def to_operator(message: Message, state: FSMContext):
    pass
