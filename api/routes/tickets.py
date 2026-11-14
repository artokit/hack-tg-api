from fastapi import APIRouter, Depends, HTTPException
from depends import get_ticket_service
from schemas.ticket import TicketCreate, TicketRead
from services.ticket_service import TicketService
from tickets.jsm import TicketSystemError

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TicketRead, status_code=201)
async def create_ticket(
    data: TicketCreate,
    service: TicketService = Depends(get_ticket_service),
):
    try:
        return await service.create(data)
    except TicketSystemError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
