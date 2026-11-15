from fastapi import APIRouter, Depends, HTTPException

from depends import get_current_user, get_technical_analytics_service
from schemas.technical_analytics import TechnicalAnalyticsRead, TechnicalRange
from services.technical_analytics import TechnicalAnalyticsService, TechnicalAnalyticsUnavailable


router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_user)])


@router.get("/technical", response_model=TechnicalAnalyticsRead, responses={503: {"description": "Metrics unavailable"}})
async def read_technical_analytics(
    range: TechnicalRange = "24h",
    service: TechnicalAnalyticsService = Depends(get_technical_analytics_service),
) -> TechnicalAnalyticsRead:
    try:
        return await service.read(range)
    except TechnicalAnalyticsUnavailable as error:
        raise HTTPException(status_code=503, detail="Metrics unavailable") from error
