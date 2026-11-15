from pathlib import PureWindowsPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile

from depends import get_ticket_attachment_service, get_ticket_service, require_bot_token
from schemas.ticket import TicketAttachmentRead, TicketCreate, TicketRead
from services.ticket_service import TicketAttachmentService, TicketLookupError, TicketService
from tickets.jsm import TicketSystemError

router = APIRouter(prefix="/tickets", tags=["tickets"])
private_router = APIRouter(
    prefix="/private/tickets", tags=["tickets"], dependencies=[Depends(require_bot_token)],
)
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


@router.post("", response_model=TicketRead, status_code=201)
async def create_ticket(
    data: TicketCreate,
    service: TicketService = Depends(get_ticket_service),
):
    try:
        return await service.create(data)
    except TicketSystemError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@private_router.post(
    "/{ticket_id}/attachments",
    response_model=TicketAttachmentRead,
    status_code=201,
)
async def attach_ticket_file(
    ticket_id: int = Path(ge=1),
    file: UploadFile = File(...),
    public: bool = Form(False),
    service: TicketAttachmentService = Depends(get_ticket_attachment_service),
):
    try:
        filename = PureWindowsPath(file.filename or "").name
        if not filename or filename in {".", ".."} or len(filename) > 255 or any(
            ord(character) < 32 for character in filename
        ):
            raise HTTPException(status_code=400, detail="Некорректное имя файла")
        if file.size is not None and file.size > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="Файл должен быть не больше 10 МиБ")
        content = await file.read(MAX_ATTACHMENT_BYTES + 1)
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="Файл должен быть не больше 10 МиБ")
        if not content:
            raise HTTPException(status_code=400, detail="Файл не должен быть пустым")
        return await service.attach_file(
            ticket_id,
            filename,
            content,
            file.content_type or "application/octet-stream",
            public,
        )
    except TicketLookupError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except TicketSystemError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    finally:
        await file.close()
