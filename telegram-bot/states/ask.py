from aiogram.fsm.state import StatesGroup, State


class AskStates(StatesGroup):
    user_ask = State()
