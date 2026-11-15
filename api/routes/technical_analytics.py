from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime

from depends import get_current_user, get_support_request_service, get_technical_analytics_service
from schemas.support_requests import RequestCostRead
from schemas.technical_analytics import TechnicalAnalyticsRead, TechnicalRange
from services.support_requests import SupportRequestService
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


@router.get("/request-cost", response_model=RequestCostRead)
async def read_request_cost(
    from_at: AwareDatetime | None = None,
    to_at: AwareDatetime | None = None,
    service: SupportRequestService = Depends(get_support_request_service),
) -> RequestCostRead:
    if from_at is not None and to_at is not None and from_at >= to_at:
        raise HTTPException(status_code=422, detail="from_at must precede to_at")
    return await service.cost_summary(from_at, to_at)
