import asyncio
from base64 import b64encode

import httpx
from pydantic import BaseModel, ValidationError

from models.rag import RagUnavailable
from schemas.rag import ChunkPlan, FactCheck, ProposedFact, QueryPlan, VisualReading


class RagModel:
    def __init__(self, http: httpx.AsyncClient, token: str | None, *, url: str = "http://flue:3000"):
        self.http = http
        self.url = url.rstrip("/") + "/internal/rag/model"
        self.headers = {"X-Bot-Token": token} if token else {}
        self.slots = asyncio.Semaphore(8)

    async def run[T: BaseModel](
        self, operation: str, output: type[T], data: dict, image: bytes | None = None,
    ) -> T:
        request = {"operation": operation, "data": data, "schema": output.model_json_schema()}
        if image is not None:
            request["image"] = b64encode(image).decode("ascii")
        async with self.slots:
            for attempt in range(2):
                try:
                    response = await self.http.post(self.url, json=request, headers=self.headers, timeout=22)
                    if response.status_code == 422 and attempt == 0:
                        continue
                    response.raise_for_status()
                    return output.model_validate(response.json())
                except ValidationError as error:
                    if attempt:
                        raise RagUnavailable("flue_model_invalid_output") from error
                except (httpx.HTTPError, ValueError) as error:
                    raise RagUnavailable("flue_model_unavailable") from error
        raise RagUnavailable("flue_model_invalid_output")

    async def read_visual(self, image: bytes, kind: str, context: str) -> VisualReading:
        return await self.run("read_visual", VisualReading, {"kind": kind, "nearby_text": context}, image)

    async def plan_chunks(self, blocks: list[dict], correction: str = "") -> ChunkPlan:
        return await self.run("plan_chunks", ChunkPlan, {"blocks": blocks, "correction": correction})

    async def plan_query(self, question: str, standalone: str | None, ids: tuple[str, ...]) -> QueryPlan:
        return await self.run(
            "plan_query", QueryPlan,
            {"question": question, "context_question": standalone, "exact_ids": ids},
        )

    async def propose(self, question: str, sources: list[dict]) -> ProposedFact:
        return await self.run("propose", ProposedFact, {"question": question, "sources": sources})

    async def verify(
        self, question: str, statement: str, sources: list[dict], original_question: str,
    ) -> FactCheck:
        return await self.run(
            "verify", FactCheck,
            {"question": question, "original_question": original_question, "statement": statement, "sources": sources},
        )
