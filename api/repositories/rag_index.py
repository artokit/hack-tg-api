import asyncio
import hashlib
import json
import math
from uuid import UUID, uuid5

import httpx

from config import RagSettings
from models.rag import RagUnavailable


VECTOR_SIZE = 4096
PAGE_SIZE = 24
POINT_NAMESPACE = UUID("345d918b-0f30-4213-88e5-fd11e9187512")
QUERY_INSTRUCTION = (
    "Given a question, retrieve documentation passages containing the exact entity, "
    "condition, or fact needed to answer it."
)


class RagIndex:
    def __init__(self, settings: RagSettings, http: httpx.AsyncClient):
        self.http = http
        self.collection = settings.rag_collection
        self.qdrant = str(settings.rag_qdrant_url).rstrip("/")
        self.embedding = str(settings.rag_embedding_base_url).rstrip("/") + "/embeddings"
        self.model = settings.rag_embedding_model
        self.embedding_options = (
            {"provider": {"data_collection": "deny", "zdr": True}}
            if settings.rag_embedding_base_url and settings.rag_embedding_base_url.host == "openrouter.ai"
            else {}
        )
        self.qdrant_headers = (
            {"api-key": settings.rag_qdrant_api_key.get_secret_value()}
            if settings.rag_qdrant_api_key else {}
        )
        self.embedding_headers = (
            {"Authorization": "Bearer " + settings.rag_embedding_api_key.get_secret_value()}
            if settings.rag_embedding_api_key else {}
        )
        self.key = hashlib.sha256(json.dumps(
            [self.qdrant, self.collection, self.embedding, self.model, VECTOR_SIZE, QUERY_INSTRUCTION]
        ).encode()).hexdigest()

    async def vectors(self, texts: list[str]) -> list[list[float]]:
        try:
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
        except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError) as error:
            raise RagUnavailable("embedding_unavailable") from error

    async def request(self, method: str, path: str = "", body=None, *, allow_missing=False):
        try:
            response = await self.http.request(
                method, f"{self.qdrant}/collections/{self.collection}{path}",
                headers=self.qdrant_headers, json=body,
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

    async def semantic(self, text: str, versions: list[str]) -> list[dict]:
        if not versions:
            return []
        [vector] = await self.vectors([f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"])
        result = await self.request("POST", "/points/query", {
            "query": vector, "filter": self.filter(versions),
            "limit": 8, "with_payload": True,
        })
        return [row["payload"] for row in result["points"]]

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
