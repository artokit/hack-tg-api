from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RagImportEvent
from models.document_analytics import DocumentFormat, DocumentSize


MIB = 1024 * 1024


class DocumentAnalyticsRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def summary(
        self, format: DocumentFormat | None, size: DocumentSize | None, from_at: datetime | None, to_at: datetime,
    ):
        size_bytes = RagImportEvent.size_bytes
        filters = [RagImportEvent.accepted_at < to_at]
        if from_at is not None:
            filters.append(RagImportEvent.accepted_at >= from_at)
        if format is not None:
            filters.append(RagImportEvent.format == format)
        if size == "up_to_1_mb":
            filters.append(size_bytes < MIB)
        elif size == "1_to_5_mb":
            filters.append(size_bytes.between(MIB, 5 * MIB))
        elif size == "over_5_mb":
            filters.append(size_bytes > 5 * MIB)

        result = await self._session.execute(select(
            func.count().filter(*filters).label("upload_count"),
            func.coalesce(func.sum(size_bytes).filter(*filters), 0).label("total_size_bytes"),
            func.count(size_bytes).filter(*filters).label("known_size_count"),
            func.avg(RagImportEvent.processing_ms).filter(*filters).label("mean_processing_ms"),
            func.count(RagImportEvent.processing_ms).filter(*filters).label("timed_count"),
            func.min(RagImportEvent.accepted_at).label("first_recorded_at"),
            func.count().filter(*filters, RagImportEvent.format == "pdf").label("pdf_count"),
            func.count().filter(*filters, RagImportEvent.format.in_(("doc", "docx"))).label("doc_docx_count"),
        ).where(RagImportEvent.excluded.is_(False)))
        return result.one()
