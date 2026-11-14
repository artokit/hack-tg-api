from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from config import BOT_API_TOKEN
from repositories.file_repository import FileRepository
from services.file_service import FileService

router = APIRouter()


def file_service_depends():
    return FileService(FileRepository())


@router.post("/file")
async def upload_file(file: UploadFile, file_service: Annotated[FileService, Depends(file_service_depends)]):
    return await file_service.upload_file(file)


@router.get("/file/{file_id}")
async def get_file(file_id: UUID, file_service: Annotated[FileService, Depends(file_service_depends)]):
    return await file_service.get_file(file_id)


@router.get("/file/{file_id}/content")
async def get_content(
    file_id: UUID, file_service: Annotated[FileService, Depends(file_service_depends)],
    byte_range: Annotated[str | None, Header(alias="Range", max_length=100)] = None,
    bot_token: Annotated[str | None, Header(alias="X-Bot-Token")] = None,
):
    if not BOT_API_TOKEN or not bot_token or not compare_digest(BOT_API_TOKEN.encode(), bot_token.encode()):
        raise HTTPException(status_code=401)
    return await file_service.get_content(file_id, byte_range)
