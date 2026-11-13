from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

TelegramUserId = Annotated[int, Field(gt=0, le=2**63 - 1)]


class ResetRequest(BaseModel):
    telegram_user_id: TelegramUserId


class ChatRequest(ResetRequest):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
    ]


class ChatResponse(BaseModel):
    answer: str


class TurnMessage(ChatRequest):
    turn_id: UUID
