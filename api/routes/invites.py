from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from depends import get_current_user, get_invite_service, require_bot_token
from schemas.employees import EmployeeRead
from schemas.invites import InviteAccept, InviteCreate, InviteCreated, InvitePage, InviteRead
from services.invites import InviteService

router = APIRouter(
    prefix="/invites", tags=["invites"], dependencies=[Depends(get_current_user)]
)
private_router = APIRouter(
    prefix="/private/invites", tags=["invites"], dependencies=[Depends(require_bot_token)]
)


@router.post("", response_model=InviteCreated, status_code=201)
async def create_invite(
    data: InviteCreate,
    service: InviteService = Depends(get_invite_service),
):
    try:
        return await service.create(data)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("", response_model=InvitePage)
async def get_invites(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: InviteService = Depends(get_invite_service),
):
    return await service.get_all(page, page_size)


@router.get("/{invite_id}", response_model=InviteRead)
async def get_invite(
    invite_id: UUID,
    service: InviteService = Depends(get_invite_service),
):
    try:
        return await service.get_by_id(invite_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Invite not found") from error


@router.delete("/{invite_id}", status_code=204)
async def delete_invite(
    invite_id: UUID,
    service: InviteService = Depends(get_invite_service),
):
    try:
        await service.delete(invite_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Invite not found") from error
    return Response(status_code=204)


@private_router.post("/{invite_id}/accept", response_model=EmployeeRead, status_code=201)
async def accept_invite(
    invite_id: UUID,
    data: InviteAccept,
    service: InviteService = Depends(get_invite_service),
):
    try:
        return await service.accept(invite_id, data)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Invite not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Employee already exists") from error
