from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from routes.dependencies import get_async_session
from schemas.ticket import TicketCreate, TicketRead
from services.ticket_service import service as ticket_service
from tickets.jsm import TicketSystemError

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TicketRead, status_code=201)
async def create_ticket(
    data: TicketCreate,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await ticket_service.create(session, data)
    except TicketSystemError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
