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


class VisualRow(BaseModel):
    cells: list[str] = Field(max_length=40)


class VisualReading(BaseModel):
    text: str = Field(max_length=18000)
    columns: list[str] = Field(default_factory=list, max_length=40)
    rows: list[VisualRow] = Field(default_factory=list, max_length=150)


class PlannedGroup(BaseModel):
    first: int
    last: int
    related: list[int] = Field(default_factory=list, max_length=8)


class ChunkPlan(BaseModel):
    groups: list[PlannedGroup] = Field(min_length=1, max_length=36)


class QueryPart(BaseModel):
    question: str = Field(min_length=1, max_length=1200)
    exact_id: str | None = Field(default=None, max_length=40)


class QueryPlan(BaseModel):
    parts: list[QueryPart] = Field(min_length=1, max_length=6)


class ProposedFact(BaseModel):
    status: Literal["supported", "ambiguous", "unsupported"]
    statement: str = Field(default="", max_length=450)
    evidence_ids: list[str] = Field(default_factory=list, max_length=3)
    clarification: str = Field(default="", max_length=240)


class CitationSelection(BaseModel):
    id: str
    quote: str | None = Field(default=None, max_length=330)


class FactCheck(BaseModel):
    supported: bool
    citations: list[CitationSelection] = Field(default_factory=list, max_length=3)
