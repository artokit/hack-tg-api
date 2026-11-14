from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TicketCreate(BaseModel):
    user_id: int


class TicketRead(TicketCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: str
    status: str
    taken_by_username: str | None = None
    created_at: datetime


class TicketMessageCreate(BaseModel):
    sender: str
    text: str


class TicketMessageRead(TicketMessageCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    created_at: datetime


class TicketTake(BaseModel):
    taken_by_username: str
