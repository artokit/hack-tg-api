from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from routes.dependencies import get_user_service
from schemas.users import UserCreate, UserRead
from services.users import UserService

router = APIRouter(prefix="/users", tags=["users"])
UserServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.post("")
async def create_user(data: UserCreate, service: UserServiceDep) -> UserRead:
    user = await service.register(data.telegram_user_id, data.username)
    return UserRead.model_validate(user)


@router.get("/{user_id}")
async def get_user(user_id: int, service: UserServiceDep) -> UserRead:
    if not -(2**31) <= user_id < 2**31:
        raise HTTPException(404, "User not found")
    user = await service.get(user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return UserRead.model_validate(user)
