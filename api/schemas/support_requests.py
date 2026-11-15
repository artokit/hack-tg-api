from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


CloseReason = Literal[
    "confirmed", "thanks", "feedback_timeout", "clarification_timeout", "details_timeout",
    "technical_timeout", "reset", "delivery_failed", "rag_exhausted", "operator_requested",
]


class SupportRequestCreate(BaseModel):
    id: UUID
    instance_id: str = Field(min_length=1)
    telegram_chat_id: int
    category_id: str | None = Field(default=None, max_length=100)
    opened_at: AwareDatetime
    closed_at: AwareDatetime
    is_resolved: bool | None
    close_reason: CloseReason
    model_cost_rub: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=9)

    @model_validator(mode="after")
    def validate_outcome(self) -> "SupportRequestCreate":
        expected = {
            "confirmed": True, "thanks": True, "details_timeout": False,
            "rag_exhausted": False, "operator_requested": False,
        }.get(self.close_reason)
        if self.closed_at < self.opened_at or self.is_resolved is not expected:
            raise ValueError("Invalid support request outcome")
        return self


class SupportRequestRead(SupportRequestCreate):
    model_config = ConfigDict(from_attributes=True)


class RequestCostRead(BaseModel):
    currency: Literal["RUB"] = "RUB"
    closed_count: int
    priced_count: int
    total: float | None
    mean: float | None


class SupportTicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    external_key: str | None
