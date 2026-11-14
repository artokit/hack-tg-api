from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    telegram_user_id: Annotated[int, Field(ge=-(2**63), lt=2**63)]
    username: Annotated[str | None, Field(max_length=255)] = None


class UserRead(UserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
