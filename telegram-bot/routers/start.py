from services.user_service import service as user_service
from services.departament_service import service as departament_service
from aiogram.filters import Command
from aiogram.types import Message
from keyboards import start as keyboards_start
from aiogram import Router
import utils

router = Router()


@router.message(Command("start"))
async def start(message: Message):
    # 4. Пишет админ тг бота и он может посмотреть либо все возможные департаменты, либо изменить их, либо создать новый +
    if utils.user_is_admin(message.chat.id):
        return await message.answer("Привет!\nВыберите действие.", markup=keyboards_start.get_admin_start_keyboard())
    # Здесь может быть несколкьо сценариев.
    # 1. Пишет хз кто и ему в ответ приходит что он не ялвляется сотрудником +
    # 2. Пишет начальник департамента и ему отправляется клава с добавление новых документов
    # 3. Пишет обычный сотрудник и ему отправляется текст типо "Напишите вопрос который вас интересует"
    user = await user_service.get_user_by_id(message.chat.id)

    if user is None:
        return await message.answer("Вас нету в системе :(\nВозможно вас ещё не добавили ни в один из отделов. Обратитесь к своему руководителю отдела")

    ids = await departament_service.get_user_departments_ids_by_user_id(message.chat.id)

    if not ids:
        return await message.answer(
            "Вас нету в системе :(\nВозможно вас ещё не добавили ни в один из отделов. Обратитесь к своему руководителю отдела")

    kb = keyboards_start.
