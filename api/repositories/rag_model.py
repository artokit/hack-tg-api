import asyncio
from base64 import b64encode

import httpx
from models.rag import RagUnavailable


class RagModel:
    def __init__(self, http: httpx.AsyncClient, token: str | None, *, url: str = "http://flue:3000"):
        self.http = http
        self.url = url.rstrip("/") + "/internal/rag/model"
        self.headers = {"X-Bot-Token": token} if token else {}
        self.slots = asyncio.Semaphore(8)

    async def run(self, operation: str, data: dict, image: bytes | None = None) -> dict:
        request = {"operation": operation, "data": data}
        if image is not None:
            request["image"] = b64encode(image).decode("ascii")
        async with self.slots:
            for attempt in range(2):
                try:
                    response = await self.http.post(self.url, json=request, headers=self.headers, timeout=22)
                    if response.status_code == 422 and attempt == 0:
                        continue
                    response.raise_for_status()
                    return response.json()
                except (httpx.HTTPError, ValueError) as error:
                    raise RagUnavailable("flue_model_unavailable") from error
        raise RagUnavailable("flue_model_invalid_output")

    async def read_visual(self, image: bytes, kind: str, context: str) -> dict:
        return await self.run("read_visual", {"kind": kind, "nearby_text": context}, image)

    async def plan_chunks(self, blocks: list[dict], correction: str = "") -> dict:
        return await self.run("plan_chunks", {"blocks": blocks, "correction": correction})
