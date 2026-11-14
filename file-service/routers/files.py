from typing import Annotated
from fastapi import APIRouter, UploadFile, Depends
from repositories.file_repository import FileRepository
from services.file_service import FileService

router = APIRouter()


def file_service_depends():
    return FileService(FileRepository())


@router.post("/file")
async def upload_file(file: UploadFile, file_service: Annotated[FileService, Depends(file_service_depends)]):
    return await file_service.upload_file(file)


@router.get("/file/{file_id}")
async def get_file(file_id: str, file_service: Annotated[FileService, Depends(file_service_depends)]):
    return await file_service.get_file(file_id)
