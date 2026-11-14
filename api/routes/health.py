from fastapi import APIRouter, Depends, HTTPException

from depends import get_health_service
from services.health import HealthService

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    service: HealthService = Depends(get_health_service),
) -> dict[str, str]:
    if not await service.is_available():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok"}
