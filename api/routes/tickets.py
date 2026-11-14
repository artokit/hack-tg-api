from fastapi import APIRouter, Depends, HTTPException

from depends import get_ticket_service
from schemas.tickets import (
    TicketCreate,
    TicketMessageCreate,
    TicketMessageRead,
    TicketRead,
    TicketTake,
)
from services.tickets import TicketService

router = APIRouter(tags=["tickets"])


@router.post("/tickets", response_model=TicketRead, status_code=201)
async def create_ticket(
    data: TicketCreate,
    service: TicketService = Depends(get_ticket_service),
):
    return await service.create(data)


@router.get("/tickets/by-group-id/{group_id}", response_model=TicketRead)
async def get_ticket(
    group_id: str,
    service: TicketService = Depends(get_ticket_service),
):
    ticket = await service.get_by_group_id(group_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.post("/tickets/{group_id}/messages", response_model=TicketMessageRead, status_code=201)
async def add_ticket_message(
    group_id: str,
    data: TicketMessageCreate,
    service: TicketService = Depends(get_ticket_service),
):
    try:
        return await service.add_message(group_id, data)
    except LookupError:
        raise HTTPException(status_code=404, detail="Ticket not found")


@router.get("/tickets/{group_id}/messages", response_model=list[TicketMessageRead])
async def get_ticket_messages(
    group_id: str,
    service: TicketService = Depends(get_ticket_service),
):
    try:
        return await service.get_messages(group_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Ticket not found")


@router.patch("/tickets/{group_id}", response_model=TicketRead)
async def take_ticket(
    group_id: str,
    data: TicketTake,
    service: TicketService = Depends(get_ticket_service),
):
    try:
        return await service.take(group_id, data)
    except LookupError:
        raise HTTPException(status_code=404, detail="Ticket not found")
    except ValueError:
        raise HTTPException(status_code=409, detail="Ticket already taken")
