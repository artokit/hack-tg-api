from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query

from config import InviteSettings
from depends import (
    get_invite_settings, get_support_request_service,
    get_ticket_service, require_bot_token,
)
from schemas.ticket import TicketCreate, TicketRead, TicketRecipientRead
from services.support_requests import SupportRequestConflict, SupportRequestNotFound, SupportRequestService
from services.ticket_service import TicketLookupError, TicketService
from tickets.jsm import TicketSystemError

router = APIRouter(prefix="/tickets", tags=["tickets"])
private_router = APIRouter(
    prefix="/private/tickets", tags=["tickets"], dependencies=[Depends(require_bot_token)],
)


@private_router.get("/by-external-key/{external_key}/recipient", response_model=TicketRecipientRead)
async def read_ticket_recipient(
    external_key: str = Path(min_length=3, max_length=100, pattern=r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$"),
    issue_id: str = Query(max_length=100, pattern=r"^[1-9][0-9]*$"),
    service: TicketService = Depends(get_ticket_service),
):
    try:
        request = await service.jira_recipient(external_key, issue_id)
        return TicketRecipientRead(telegram_chat_id=str(request.telegram_chat_id))
    except TicketLookupError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("", response_model=TicketRead, status_code=201)
async def create_ticket(
    data: TicketCreate,
    service: TicketService = Depends(get_ticket_service),
    support: SupportRequestService = Depends(get_support_request_service),
    token: str | None = Header(default=None, alias="X-Bot-Token", include_in_schema=False),
    settings: InviteSettings = Depends(get_invite_settings),
):
    try:
        if data.support_request_id is not None:
            require_bot_token(token, settings)
            return await support.create_ticket(data.support_request_id, data)
        return await service.create(data)
    except SupportRequestNotFound as error:
        raise HTTPException(404, "Support request not found") from error
    except SupportRequestConflict as error:
        raise HTTPException(409, "Support request cannot create another ticket") from error
    except TicketSystemError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
