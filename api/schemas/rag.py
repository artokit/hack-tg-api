from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RagJobCreated(BaseModel):
    job_id: UUID


class RagJobRead(BaseModel):
    id: UUID
    source_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    error_code: str | None
    version: str | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime


class RagAnswerRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, max_length=4096)
    standalone_question: str | None = Field(default=None, min_length=1, max_length=1600)


class RagSourceRead(BaseModel):
    id: str
    title: str
    url: str | None
    page: int | None
    section: list[str]
    identifiers: list[str] = Field(default_factory=list)
    quote: str | None
    visual: bool


class RagPartRead(BaseModel):
    question: str
    status: Literal["supported", "ambiguous", "unsupported"]
    statement: str = ""
    source_ids: list[str] = Field(default_factory=list)
    clarification: str = ""


class RagAnswerRead(BaseModel):
    status: Literal["answered", "partial", "clarify", "not_found"]
    parts: list[RagPartRead]
    sources: list[RagSourceRead]
