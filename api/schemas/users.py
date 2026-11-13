from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    telegram_user_id: int
    username: str | None = None


class UserRead(UserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
