from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EmployeeCreate(BaseModel):
    telegram_id: int
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)


class EmployeeRead(EmployeeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str | None
    is_parsed: bool
    created_at: datetime


class EmployeeTelegramUpdate(BaseModel):
    username: str | None = Field(max_length=255)
    first_name: str | None = Field(max_length=255)
    last_name: str | None = Field(max_length=255)


class EmployeePage(BaseModel):
    items: list[EmployeeRead]
    total: int
    page: int
    page_size: int
