from fastapi import APIRouter, Depends, HTTPException

from depends import get_user_service
from schemas.users import UserCreate, UserRead
from services.users import UserService

router = APIRouter(tags=["users"])


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(
    data: UserCreate,
    service: UserService = Depends(get_user_service),
):
    try:
        return await service.create(data)
    except ValueError:
        raise HTTPException(status_code=409, detail="User already exists")


@router.get("/users/by-telegram-id/{telegram_user_id}", response_model=UserRead)
async def get_user_by_telegram_id(
    telegram_user_id: int,
    service: UserService = Depends(get_user_service),
):
    user = await service.get_by_telegram_id(telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    service: UserService = Depends(get_user_service),
):
    if not -(2**31) <= user_id < 2**31:
        raise HTTPException(status_code=404, detail="User not found")
    user = await service.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
