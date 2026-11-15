import re
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
import config
from repositories.file_repository import FileRepository
from schemas.files_schemas import FileResponse


FILE_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/plain; charset=utf-8",
    "png": "image/png",
}


class FileService:
    def __init__(self, repo: FileRepository):
        self.repo = repo
        self.s3 = boto3.client(
            's3',
            endpoint_url=config.S3_STORAGE_URL,
            region_name='ru-1',
            aws_access_key_id=config.S3_ACCESS_KEY,
            aws_secret_access_key=config.S3_SECRET_KEY,  # <--- заменить
            config=Config(s3={'addressing_style': 'auto'})
        )

    @staticmethod
    def object_key(file_id: UUID, extension: str | None) -> str:
        return f"{file_id}.{extension}" if extension else str(file_id)

    async def upload_file(self, file: UploadFile) -> FileResponse:
        filename = PurePosixPath((file.filename or "file").replace("\\", "/")).name or "file"
        file_extension = PurePosixPath(filename).suffix.removeprefix(".")
        file_extension = file_extension if re.fullmatch(r"[a-zA-Z0-9]{1,16}", file_extension) else None
        file_id = uuid4()
        file_name_in_storage = self.object_key(file_id, file_extension)
        await run_in_threadpool(self.s3.upload_fileobj, file.file, config.S3_BUCKET_NAME, file_name_in_storage)
        await self.repo.add_file(filename, file_id, file_extension)
        return FileResponse(
            id=str(file_id),
            name=filename,
            extension=file_extension,
            url=f"{config.S3_STORAGE_URL}/{config.S3_BUCKET_NAME}/{file_name_in_storage}"
        )

    async def get_file(self, file_id: UUID) -> FileResponse:
        file = await self.repo.get_file_by_id(file_id)
        if file is None:
            raise HTTPException(status_code=404)
        file_name_in_storage = self.object_key(file_id, file.extension)
        return FileResponse(
            id=str(file.id),
            name=file.name,
            extension=file.extension,
            url=f"{config.S3_STORAGE_URL}/{config.S3_BUCKET_NAME}/{file_name_in_storage}"
        )

    async def put_visual(self, file_id: UUID, file: UploadFile) -> None:
        if file.size is not None and file.size > 25 * 1024 * 1024:
            raise HTTPException(status_code=413)
        if await file.read(8) != b"\x89PNG\r\n\x1a\n":
            raise HTTPException(status_code=415)
        await file.seek(0)
        if not await self.repo.reserve_visual(file_id):
            raise HTTPException(status_code=409)
        try:
            await run_in_threadpool(
                self.s3.upload_fileobj, file.file, config.S3_BUCKET_NAME, self.object_key(file_id, "png"),
            )
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=503) from error

    async def delete_file(self, file_id: UUID) -> None:
        file = await self.repo.get_file_by_id(file_id)
        if file is None:
            return
        try:
            await run_in_threadpool(
                self.s3.delete_object, Bucket=config.S3_BUCKET_NAME, Key=self.object_key(file_id, file.extension),
            )
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=503) from error
        await self.repo.delete_file(file_id)

    async def get_content(self, file_id: UUID, byte_range: str | None) -> StreamingResponse:
        file = await self.repo.get_file_by_id(file_id)
        if file is None:
            raise HTTPException(status_code=404)
        if byte_range and not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", byte_range):
            raise HTTPException(status_code=416)
        try:
            result = await run_in_threadpool(
                self.s3.get_object, Bucket=config.S3_BUCKET_NAME, Key=self.object_key(file_id, file.extension),
                **({"Range": byte_range} if byte_range else {}),
            )
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 416:
                headers = error.response["ResponseMetadata"].get("HTTPHeaders", {})
                content_range = headers.get("content-range")
                raise HTTPException(
                    status_code=416, headers={"Content-Range": content_range} if content_range else None,
                ) from error
            raise HTTPException(status_code=404 if status == 404 else 503) from error

        body = result["Body"]

        async def stream():
            try:
                while chunk := await run_in_threadpool(body.read, 65536):
                    yield chunk
            finally:
                body.close()

        extension = (file.extension or "").lower()
        disposition = "inline" if extension in {"pdf", "md"} else "attachment"
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(file.name, safe='')}",
            "Content-Length": str(result["ContentLength"]),
            "X-Content-Type-Options": "nosniff",
        }
        if "ContentRange" in result:
            headers["Content-Range"] = result["ContentRange"]
        return StreamingResponse(
            stream(), media_type=FILE_TYPES.get(extension, "application/octet-stream"), headers=headers,
            status_code=206 if "ContentRange" in result else 200,
        )
