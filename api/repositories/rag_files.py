import hashlib
import hmac
from uuid import UUID

import httpx

from models.rag import DocumentTooLarge, InvalidDocument, RagUnavailable


MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
DOCUMENT_FORMATS = {"pdf", "docx", "md"}


class RagFiles:
    def __init__(self, http: httpx.AsyncClient, base_url: str, public_url: str, token: str | None):
        self.http = http
        self.base_url = base_url.rstrip("/") + "/file-service/file"
        self.public_url = public_url.rstrip("/")
        self.token = token

    def signature(self, file_id: UUID) -> str:
        if not self.token:
            raise RagUnavailable("file_service_unconfigured")
        return hmac.new(self.token.encode(), f"rag-file:{file_id}".encode(), hashlib.sha256).hexdigest()

    def permits(self, file_id: UUID, signature: str) -> bool:
        return bool(self.token and hmac.compare_digest(self.signature(file_id), signature))

    async def upload(self, filename: str, data: bytes) -> UUID:
        if not self.token:
            raise RagUnavailable("file_service_unconfigured")
        try:
            response = await self.http.post(self.base_url, files={"file": (filename, data)})
            response.raise_for_status()
            file_id = UUID(response.json()["id"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise RagUnavailable("file_service_unavailable") from error
        return file_id

    def link(self, file_id: UUID) -> str | None:
        return f"{self.public_url}/files/{file_id}?sig={self.signature(file_id)}" if self.token else None

    async def open(self, file_id: UUID, byte_range: str | None = None) -> httpx.Response:
        if not self.token:
            raise RagUnavailable("file_service_unconfigured")
        headers = {"X-Bot-Token": self.token}
        if byte_range:
            headers["Range"] = byte_range
        request = self.http.build_request(
            "GET", f"{self.base_url}/{file_id}/content",
            headers=headers,
        )
        try:
            response = await self.http.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as error:
            raise RagUnavailable("file_service_unavailable") from error
        if response.status_code in (200, 206, 404, 416):
            return response
        await response.aclose()
        raise RagUnavailable("file_service_unavailable")

    async def load(self, file_id: UUID) -> bytes:
        response = await self.open(file_id)
        try:
            if response.status_code == 404:
                raise InvalidDocument("upload_missing")
            if response.status_code != 200:
                raise RagUnavailable("file_service_unavailable")
            return await read_document(response)
        except httpx.HTTPError as error:
            raise RagUnavailable("file_service_unavailable") from error
        finally:
            await response.aclose()


async def read_document(response: httpx.Response) -> bytes:
    data = bytearray()
    async for block in response.aiter_raw(chunk_size=65536):
        data.extend(block)
        if len(data) > MAX_DOCUMENT_BYTES:
            raise DocumentTooLarge("document_too_large")
    if not data:
        raise InvalidDocument("empty_document")
    return bytes(data)
