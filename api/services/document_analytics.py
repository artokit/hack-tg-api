import asyncio
from datetime import UTC, datetime

from models.document_analytics import DocumentFormat, DocumentSize
from repositories.document_analytics import DocumentAnalyticsRepository
from repositories.technical_analytics import PrometheusRepository, PrometheusUnavailable
from schemas.document_analytics import DocumentAnalyticsRead, DocumentFormatsRead, DocumentRange, DocumentTokensRead
from schemas.technical_analytics import TechnicalRange, WorkloadTokensRead
from services.technical_analytics import WINDOWS, token_increase, workload_tokens


class DocumentAnalyticsService:
    def __init__(self, repository: DocumentAnalyticsRepository, prometheus: PrometheusRepository | None):
        self._repository = repository
        self._prometheus = prometheus

    async def read(
        self, format: DocumentFormat | None, size: DocumentSize | None, period: DocumentRange | None,
    ) -> DocumentAnalyticsRead:
        now = datetime.now(UTC)
        window: TechnicalRange | None = "24h" if period == "1d" else period
        from_at = now - WINDOWS[window] if window is not None else None
        token_window = window or "24h"
        summary, tokens = await asyncio.gather(
            self._repository.summary(format, size, from_at, now),
            self._read_tokens(now, token_window),
        )
        return DocumentAnalyticsRead(
            range=window,
            from_at=from_at,
            to_at=now,
            upload_count=summary.upload_count,
            total_size_bytes=summary.total_size_bytes,
            known_size_count=summary.known_size_count,
            mean_processing_ms=round(summary.mean_processing_ms, 2) if summary.mean_processing_ms is not None else None,
            timed_count=summary.timed_count,
            first_recorded_at=summary.first_recorded_at,
            by_format=DocumentFormatsRead(
                pdf=summary.pdf_count,
                doc_docx=summary.doc_docx_count,
                other=summary.upload_count - summary.pdf_count - summary.doc_docx_count,
            ),
            tokens=DocumentTokensRead(from_at=now - WINDOWS[token_window], to_at=now, document_import=tokens),
        )

    async def _read_tokens(self, at: datetime, window: TechnicalRange) -> WorkloadTokensRead | None:
        if self._prometheus is None:
            return None
        try:
            samples = await self._prometheus.query(token_increase("document_import", window), at)
        except PrometheusUnavailable:
            return None
        return workload_tokens(samples, "document_import")
