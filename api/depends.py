from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.db import get_async_session
from repositories.users import UserRepository
from services.users import UserService


def get_user_service(session: AsyncSession = Depends(get_async_session)) -> UserService:
    return UserService(UserRepository(session))
