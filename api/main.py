from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.db import get_async_session
from db.models import User

app = FastAPI(title="Hackathon API")


class UserCreate(BaseModel):
    telegram_user_id: int
    username: str | None = None


class UserRead(UserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


@app.post("/users", response_model=UserRead)
async def create_user(
    data: UserCreate,
    session: AsyncSession = Depends(get_async_session),
):
    existing = await session.scalar(
        select(User).where(User.telegram_user_id == data.telegram_user_id)
    )
    if existing is not None:
        return existing

    user = User(**data.model_dump())
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@app.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_async_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
