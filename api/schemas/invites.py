from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InviteCreate(BaseModel):
    count_of_use: int = Field(default=1, ge=1, le=2**31 - 1, strict=True)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_single_use_names(self):
        if self.count_of_use != 1 and (
            self.first_name is not None or self.last_name is not None
        ):
            raise ValueError("Names can only be specified for a single-use invite")
        return self


class InviteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    count_of_use: int
    first_name: str | None
    last_name: str | None


class InviteCreated(InviteRead):
    link: str


class InvitePage(BaseModel):
    items: list[InviteRead]
    total: int
    page: int
    page_size: int


class InviteAccept(BaseModel):
    telegram_id: int = Field(ge=1, le=2**63 - 1)
    username: str | None = Field(default=None, max_length=255)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
