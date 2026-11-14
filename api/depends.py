from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.health import HealthRepository
from repositories.users import UserRepository
from services.health import HealthService
from services.users import UserService


async def get_async_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


def get_user_service(session: AsyncSession = Depends(get_async_session)) -> UserService:
    return UserService(UserRepository(session))


def get_health_service(session: AsyncSession = Depends(get_async_session)) -> HealthService:
    return HealthService(HealthRepository(session))
