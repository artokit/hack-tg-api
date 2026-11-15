from asyncio import to_thread

from fastapi import APIRouter, Depends, HTTPException, Request

from depends import require_bot_token
from models.rag import DocumentTooLarge, InvalidDocument
from schemas.telegram_attachments import TelegramAttachmentTextRead
from services.telegram_attachments import MAX_ATTACHMENT_BYTES, read_attachment_text


router = APIRouter(prefix="/private/telegram", dependencies=[Depends(require_bot_token)])


@router.post("/attachment-text", response_model=TelegramAttachmentTextRead)
async def attachment_text(request: Request, format: str):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="document_too_large")
        data.extend(chunk)
    try:
        text, truncated = await to_thread(read_attachment_text, format, bytes(data))
    except DocumentTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except InvalidDocument as error:
        reason = str(error)
        status = 415 if reason == "unsupported_format" else 422
        raise HTTPException(status_code=status, detail=reason) from error
    return TelegramAttachmentTextRead(text=text, truncated=truncated)
