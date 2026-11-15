from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from depends import get_support_request_service, require_bot_token
from schemas.support_requests import (
    SupportRequestCreate, SupportRequestRead, SupportTicketCreate, SupportTicketRead,
)
from services.support_requests import (
    SupportRequestConflict, SupportRequestNotFound, SupportRequestService,
)


router = APIRouter(
    prefix="/private/support-requests",
    tags=["support-requests"],
    dependencies=[Depends(require_bot_token)],
)


@router.post("", response_model=SupportRequestRead, status_code=201)
async def create(
    data: SupportRequestCreate, service: SupportRequestService = Depends(get_support_request_service),
):
    try:
        return await service.create(data)
    except SupportRequestConflict as error:
        raise HTTPException(409, "Support request already exists") from error


@router.get("/{request_id}", response_model=SupportRequestRead)
async def read(
    request_id: UUID, service: SupportRequestService = Depends(get_support_request_service),
):
    try:
        return await service.get(request_id)
    except SupportRequestNotFound as error:
        raise HTTPException(404, "Support request not found") from error


@router.post("/{request_id}/ticket", response_model=SupportTicketRead, status_code=201)
async def create_ticket(
    request_id: UUID, data: SupportTicketCreate,
    service: SupportRequestService = Depends(get_support_request_service),
):
    try:
        return await service.create_ticket(request_id, data)
    except SupportRequestNotFound as error:
        raise HTTPException(404, "Support request not found") from error
    except SupportRequestConflict as error:
        raise HTTPException(409, "Support request cannot create another ticket") from error


@router.get("/{request_id}/ticket", response_model=SupportTicketRead)
async def read_ticket(
    request_id: UUID, service: SupportRequestService = Depends(get_support_request_service),
):
    try:
        return await service.get_ticket(request_id)
    except SupportRequestNotFound as error:
        raise HTTPException(404, "Support ticket not found") from error
