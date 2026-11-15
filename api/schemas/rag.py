from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from models.rag import BlockKind


SOURCE_ID_PATTERN = r"^[a-zA-Z0-9_./:\-]+$"
CONFLUENCE_ID_PATTERN = r"^[1-9][0-9]{0,18}$"


class RagJobCreated(BaseModel):
    job_id: UUID
    source_id: str
    file_id: UUID | None = None


class RagUrlRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: AnyHttpUrl
    title: str | None = Field(default=None, min_length=1, max_length=250)
    source_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=SOURCE_ID_PATTERN)


class RagConfluenceImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(pattern=CONFLUENCE_ID_PATTERN)
    page_id: str = Field(pattern=CONFLUENCE_ID_PATTERN)


class RagJobRead(BaseModel):
    id: UUID
    source_id: str
    file_id: UUID | None = None
    status: Literal["queued", "running", "succeeded", "failed", "skipped"]
    error_code: str | None
    version: str | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime


class RagJobListItem(RagJobRead):
    title: str
    format: str
    size_bytes: int | None
    has_active_version: bool
    document_url: str | None


class RagJobPage(BaseModel):
    items: list[RagJobListItem]
    total: int
    page: int
    page_size: int


class RagSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, max_length=1200)
    original_question: str = Field(min_length=1, max_length=4096)
    exact_id: str | None = Field(default=None, max_length=40)
    standalone: bool = False


class RagEvidenceRead(BaseModel):
    id: str
    title: str
    source_url: str | None
    format: str
    page: int | None
    section: list[str]
    identifiers: list[str]
    kind: BlockKind
    text: str
    label: str = ""
    columns: list[str] = Field(default_factory=list)


class RagCachedEvidence(RagEvidenceRead):
    file_id: UUID | None
