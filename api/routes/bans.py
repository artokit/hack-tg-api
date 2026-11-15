from fastapi import APIRouter, Depends, HTTPException

from depends import get_ban_service, require_bot_token
from schemas.bans import BanCreate, BanRead
from services.bans import BanService
from utils.exceptions import BanUnavailableError


router = APIRouter(
    prefix="/private/bans", tags=["bans"], dependencies=[Depends(require_bot_token)],
)


@router.post("", response_model=BanRead)
async def create_ban(data: BanCreate, service: BanService = Depends(get_ban_service)):
    try:
        state = await service.create(data.telegram_id)
    except BanUnavailableError as error:
        raise HTTPException(status_code=503, detail="Ban storage unavailable") from error
    return BanRead(
        telegram_id=data.telegram_id,
        ban_level=state.ban_level,
        retry_after_seconds=state.retry_after_seconds,
        expires_at_ms=state.expires_at_ms,
    )
