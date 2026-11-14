from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_names(self):
        if not self.model_fields_set:
            raise ValueError("At least one name field must be provided")
        return self


class EmployeeTelegramUpdate(BaseModel):
    username: str | None = Field(max_length=255)
    first_name: str | None = Field(max_length=255)
    last_name: str | None = Field(max_length=255)


class EmployeePage(BaseModel):
    items: list[EmployeeRead]
    total: int
    page: int
    page_size: int
