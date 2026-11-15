from typing import Annotated

from fastapi import APIRouter, Depends, Query

from depends import get_current_user, get_document_analytics_service
from models.document_analytics import DocumentFormat, DocumentSize
from schemas.document_analytics import DocumentAnalyticsRead, DocumentRange
from services.document_analytics import DocumentAnalyticsService


router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_user)])


@router.get("/documents", response_model=DocumentAnalyticsRead)
async def read_document_analytics(
    service: Annotated[DocumentAnalyticsService, Depends(get_document_analytics_service)],
    range: Annotated[DocumentRange | None, Query(description="Период загрузок, без параметра — вся история")] = None,
    format: Annotated[DocumentFormat | None, Query(description="Формат документа")] = None,
    size: Annotated[DocumentSize | None, Query(description="Интервал размера: <1, 1–5 включительно, >5 МиБ")] = None,
) -> DocumentAnalyticsRead:
    return await service.read(format, size, range)
