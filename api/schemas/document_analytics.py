from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from schemas.technical_analytics import TechnicalRange, WorkloadTokensRead


DocumentRange = Literal["1h", "1d", "24h", "7d"]


class DocumentFormatsRead(BaseModel):
    pdf: int
    doc_docx: int
    other: int


class DocumentTokensRead(BaseModel):
    from_at: datetime
    to_at: datetime
    document_import: WorkloadTokensRead | None


class DocumentAnalyticsRead(BaseModel):
    range: TechnicalRange | None
    from_at: datetime | None
    to_at: datetime
    upload_count: int
    total_size_bytes: int
    known_size_count: int
    mean_processing_ms: float | None
    timed_count: int
    first_recorded_at: datetime | None
    by_format: DocumentFormatsRead
    tokens: DocumentTokensRead
