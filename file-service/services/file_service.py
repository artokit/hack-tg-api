import uuid
import boto3
from botocore.config import Config
from fastapi import UploadFile, HTTPException
import config
from repositories.file_repository import FileRepository
from schemas.files_schemas import FileResponse


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
    def __get_file_extension(file_name) -> str:
        if '.' in file_name:
            return file_name.split('.')[-1]

    async def upload_file(self, file: UploadFile) -> FileResponse:
        file_extension = FileService.__get_file_extension(file.filename)
        file_id = uuid.uuid4()
        file_name_in_storage = f"{file_id}.{file_extension}"
        self.s3.put_object(Bucket=config.S3_BUCKET_NAME, Key='new_file', Body='test_body')
        self.s3.upload_fileobj(file.file, config.S3_BUCKET_NAME, file_name_in_storage)
        await self.repo.add_file(file.filename, file_id, file_extension)
        return FileResponse(
            id=str(file_id),
            name=file.filename,
            extension=file_extension,
            url=f"{config.S3_STORAGE_URL}/{config.S3_BUCKET_NAME}/{file_name_in_storage}"
        )

    async def get_file(self, file_id: str) -> FileResponse:
        file = await self.repo.get_file_by_id(file_id)
        if file is None:
            raise HTTPException(status_code=404)
        print(file)
        print(file.extension)
        print(file.id)
        print(file.name)
        file_name_in_storage = f"{file_id}.{file.extension}" if file.extension else file_id
        return FileResponse(
            id=file.id,
            name=file.name,
            extension=file.extension,
            url=f"{config.S3_STORAGE_URL}/{config.S3_BUCKET_NAME}/{file_name_in_storage}"
        )