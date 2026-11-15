from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_id: int = Field(strict=True, gt=0, le=9223372036854775807)


class BanRead(BaseModel):
    telegram_id: int
    ban_level: int = Field(ge=1, le=3)
    retry_after_seconds: int = Field(gt=0, le=600)


class UserBannedRead(BaseModel):
    code: Literal["user_banned"] = "user_banned"
    retry_after_seconds: int = Field(gt=0, le=600)
