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


class RagSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, max_length=1200)
    original_question: str = Field(min_length=1, max_length=4096)
    exact_id: str | None = Field(default=None, max_length=40)
