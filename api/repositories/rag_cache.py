import hashlib
import json
import logging
import re

from redis.asyncio import Redis
from redis.exceptions import RedisError


log = logging.getLogger(__name__)


class RagCache:
    ttl_seconds = 86_400

    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    def key(
        index_key: str, versions: list[str], question: str, exact_id: str | None, *, include_visual: bool = False,
    ) -> str:
        snapshot = hashlib.sha256(json.dumps(sorted(versions)).encode()).hexdigest()
        query = hashlib.sha256(json.dumps([question, exact_id]).encode()).hexdigest()
        namespace = "v1-visual" if include_visual else "v1"
        return f"rag:search:{namespace}:{index_key}:{snapshot}:{query}"

    async def get(self, key: str) -> bytes | None:
        try:
            return await self.redis.get(key)
        except RedisError as error:
            log.debug("RAG cache read unavailable (%s)", type(error).__name__)
            return None

    async def set(self, key: str, value: bytes) -> None:
        try:
            await self.redis.set(key, value, ex=self.ttl_seconds)
        except RedisError as error:
            log.debug("RAG cache write unavailable (%s)", type(error).__name__)

    async def get_by_original(self, original_key: str) -> bytes | None:
        suffix = await self.get(f"{original_key}:original")
        if not isinstance(suffix, bytes) or not re.fullmatch(rb"[0-9a-f]{64}", suffix):
            return None
        scope, _, _ = original_key.rpartition(":")
        return await self.get(f"{scope}:{suffix.decode('ascii')}")

    async def bind_original(self, original_key: str, query_key: str) -> None:
        _, _, suffix = query_key.rpartition(":")
        await self.set(f"{original_key}:original", suffix.encode("ascii"))
