import asyncio
import hashlib
import json
import logging
import math
from urllib.parse import urlsplit
from uuid import UUID, uuid5

import httpx

from models.rag import RagUnavailable


VECTOR_SIZE = 4096
PAGE_SIZE = 24
log = logging.getLogger(__name__)
POINT_NAMESPACE = UUID("345d918b-0f30-4213-88e5-fd11e9187512")
QUERY_INSTRUCTION = (
    "Given a question, retrieve documentation passages containing the exact entity, "
    "condition, or fact needed to answer it."
)


class RagIndex:
    def __init__(
        self, http: httpx.AsyncClient, base_url: str, key: str | None,
        *, qdrant: str = "http://qdrant:6333", collection: str = "bars_docs_qwen3_v1",
    ):
        self.http = http
        self.collection = collection
        self.qdrant = qdrant.rstrip("/")
        self.embedding = base_url.rstrip("/") + "/embeddings"
        openrouter = urlsplit(base_url).hostname == "openrouter.ai"
        self.model = "qwen/qwen3-embedding-8b" if openrouter else "Qwen/Qwen3-Embedding-8B"
        self.embedding_options = (
            {"provider": {"data_collection": "deny", "zdr": True}}
            if openrouter else {}
        )
        self.embedding_headers = {"Authorization": "Bearer " + key} if key else {}
        self.key = hashlib.sha256(json.dumps(
            [self.qdrant, self.collection, self.embedding, self.model, VECTOR_SIZE, QUERY_INSTRUCTION]
        ).encode()).hexdigest()

    async def vectors(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(3):
            try:
                return await self.request_vectors(texts)
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                log.warning("RAG embedding request returned %s (batch=%s)", status, len(texts))
                if len(texts) > 1 and status in (408, 413, 429, 500, 502, 503, 504):
                    break
                if status not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    raise RagUnavailable("embedding_unavailable") from error
            except httpx.TransportError as error:
                log.warning("RAG embedding transport error %s (batch=%s)", type(error).__name__, len(texts))
                if len(texts) > 1:
                    break
                if attempt == 2:
                    raise RagUnavailable("embedding_unavailable") from error
            except (KeyError, TypeError, ValueError, OverflowError) as error:
                log.warning("RAG embedding response validation failed (%s)", type(error).__name__)
                raise RagUnavailable("embedding_unavailable") from error
            await asyncio.sleep(2 ** attempt)
        middle = len(texts) // 2
        await asyncio.sleep(1)
        return [*await self.vectors(texts[:middle]), *await self.vectors(texts[middle:])]

    async def request_vectors(self, texts: list[str]) -> list[list[float]]:
        response = await self.http.post(
            self.embedding, headers=self.embedding_headers,
            json={
                "model": self.model, "input": texts, "encoding_format": "float",
                **self.embedding_options,
            },
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda row: row["index"])
        if [row["index"] for row in data] != list(range(len(texts))):
            raise ValueError("incorrect vector indices")
        vectors = [row["embedding"] for row in data]
        if any(
            len(vector) != VECTOR_SIZE or not all(math.isfinite(value) for value in vector)
            or not any(vector)
            for vector in vectors
        ):
            raise ValueError("incorrect vector values or dimension")
        return vectors

    async def request(self, method: str, path: str = "", body=None, *, allow_missing=False):
        try:
            response = await self.http.request(
                method, f"{self.qdrant}/collections/{self.collection}{path}",
                json=body,
            )
            if response.status_code == 404 and allow_missing:
                return None
            response.raise_for_status()
            return response.json()["result"]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise RagUnavailable("index_unavailable") from error

    async def prepare(self) -> None:
        info = await self.request("GET", allow_missing=True)
        if info is None:
            await self.request("PUT", body={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}})
            info = await self.request("GET")
        vectors = info["config"]["params"]["vectors"]
        if vectors.get("size") != VECTOR_SIZE or vectors.get("distance") != "Cosine":
            raise RagUnavailable("index_incompatible")
        for field in ("version", "identifiers", "block_ids"):
            if field not in info["payload_schema"]:
                await self.request(
                    "PUT", "/index?wait=true", {"field_name": field, "field_schema": "keyword"}
                )
            elif info["payload_schema"][field]["data_type"] != "keyword":
                raise RagUnavailable("index_incompatible")

    async def write(self, version: str, entries: list[dict]) -> None:
        await self.prepare()
        async def write_batch(start: int) -> None:
            batch = entries[start:start + PAGE_SIZE]
            vectors = await self.vectors([entry["search_text"] for entry in batch])
            points = [
                {
                    "id": str(uuid5(POINT_NAMESPACE, f"{version}:{start + offset}")),
                    "vector": vector,
                    "payload": {key: value for key, value in entry.items() if key != "search_text"},
                }
                for offset, (entry, vector) in enumerate(zip(batch, vectors, strict=True))
            ]
            await self.request("PUT", "/points?wait=true", {"points": points})
            found = await self.request("POST", "/points", {
                "ids": [point["id"] for point in points], "with_payload": True,
            })
            if {row["id"]: row["payload"] for row in found} != {
                point["id"]: point["payload"] for point in points
            }:
                raise RagUnavailable("index_verification_failed")

        for offset in range(0, len(entries), 3 * PAGE_SIZE):
            batches = range(offset, min(offset + 3 * PAGE_SIZE, len(entries)), PAGE_SIZE)
            results = await asyncio.gather(
                *(write_batch(start) for start in batches), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        count = await self.request("POST", "/points/count", {
            "filter": self.filter([version]), "exact": True,
        })
        if count["count"] != len(entries):
            raise RagUnavailable("index_verification_failed")

    async def exact(self, identifier: str, versions: list[str]) -> list[dict]:
        if not versions:
            return []
        result = await self.request("POST", "/points/scroll", {
            "filter": self.filter(versions, identifier), "limit": 48, "with_payload": True,
        })
        return sorted(
            (row["payload"] for row in result["points"]),
            key=lambda chunk: (chunk["source_id"], chunk["order"]),
        )

    async def semantic(
        self, text: str, versions: list[str], *, include_visual: bool = False,
    ) -> tuple[list[dict], list[dict] | None]:
        if not versions:
            return [], []
        [vector] = await self.vectors([f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"])
        async def query(filter_: dict, limit: int) -> list[dict]:
            result = await self.request("POST", "/points/query", {
                "query": vector, "filter": filter_, "limit": limit, "with_payload": True,
            })
            return [row["payload"] for row in result["points"]]

        if not include_visual:
            return await query(self.filter(versions), 8), []
        visual_filter = self.filter(versions)
        visual_filter["must"].append({"key": "evidence[].kind", "match": {"any": ["visual", "scan"]}})
        visual_filter["should"] = [
            {"key": "format", "match": {"value": "pdf"}},
            {"key": "has_visual_file", "match": {"value": True}},
        ]
        chunks, visuals = await asyncio.gather(
            query(self.filter(versions), 8), query(visual_filter, 24), return_exceptions=True,
        )
        if isinstance(chunks, BaseException):
            raise chunks
        if isinstance(visuals, RagUnavailable):
            log.warning("RAG visual candidate search unavailable")
            return chunks, None
        if isinstance(visuals, BaseException):
            raise visuals
        return chunks, visuals

    async def related(self, ids: list[str], versions: list[str]) -> list[dict]:
        if not ids:
            return []
        filter_ = self.filter(versions)
        filter_["must"].append({"key": "block_ids", "match": {"any": ids}})
        result = await self.request("POST", "/points/scroll", {
            "filter": filter_, "limit": len(ids), "with_payload": True,
        })
        return [row["payload"] for row in result["points"]]

    async def discard(self, version: str) -> None:
        await self.request("POST", "/points/delete?wait=true", {"filter": self.filter([version])},
                           allow_missing=True)

    @staticmethod
    def filter(versions: list[str], identifier: str | None = None) -> dict:
        must = [{"key": "version", "match": {"any": versions}}]
        if identifier:
            must.append({"key": "identifiers", "match": {"value": identifier}})
        return {"must": must}
