from datetime import datetime

from pydantic import BaseModel

from schemas.technical_analytics import WorkloadTokensRead


class DocumentFormatsRead(BaseModel):
    pdf: int
    doc_docx: int
    other: int


class DocumentTokensRead(BaseModel):
    from_at: datetime
    to_at: datetime
    document_import: WorkloadTokensRead | None


class DocumentAnalyticsRead(BaseModel):
    upload_count: int
    total_size_bytes: int
    known_size_count: int
    mean_processing_ms: float | None
    timed_count: int
    first_recorded_at: datetime | None
    by_format: DocumentFormatsRead
    tokens: DocumentTokensRead
