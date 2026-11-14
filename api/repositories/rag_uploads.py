import asyncio
import logging
from pathlib import Path
from tempfile import gettempdir
from uuid import UUID

from models.rag import InvalidDocument, RagImport


log = logging.getLogger(__name__)


class RagUploads:
    def __init__(self, index_key: str):
        self.directory = Path(gettempdir()) / f"bars-rag-{index_key}"

    async def save(self, job_id: UUID, data: bytes) -> None:
        await asyncio.to_thread(self.write, job_id, data)

    def write(self, job_id: UUID, data: bytes) -> None:
        self.directory.mkdir(mode=0o700, exist_ok=True)
        file = (self.directory / str(job_id)).open("xb")
        try:
            with file:
                file.write(data)
        except OSError:
            self.discard(job_id)
            raise

    async def load(self, job: RagImport) -> bytes:
        try:
            return await asyncio.to_thread((self.directory / str(job.id)).read_bytes)
        except FileNotFoundError as error:
            raise InvalidDocument("upload_missing") from error

    def discard(self, job_id: UUID) -> None:
        try:
            (self.directory / str(job_id)).unlink(missing_ok=True)
        except OSError as error:
            log.warning("RAG could not remove upload %s (%s)", job_id, type(error).__name__)
