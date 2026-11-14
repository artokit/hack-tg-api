from fastapi import Request
from sqlalchemy.ext.asyncio import async_sessionmaker

from services.users import UserService


def get_user_service(request: Request) -> UserService:
    return request.app.state.user_service


async def get_async_session(request: Request):
    session_maker = async_sessionmaker(
        request.app.state.engine, expire_on_commit=False
    )
    async with session_maker() as session:
        yield session
