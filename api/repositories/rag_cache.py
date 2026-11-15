import hashlib
import json
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError


log = logging.getLogger(__name__)


class RagCache:
    ttl_seconds = 86_400

    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    def key(index_key: str, versions: list[str], question: str, exact_id: str | None) -> str:
        snapshot = hashlib.sha256(json.dumps(sorted(versions)).encode()).hexdigest()
        query = hashlib.sha256(json.dumps([question, exact_id]).encode()).hexdigest()
        return f"rag:search:v1:{index_key}:{snapshot}:{query}"

    async def get(self, key: str) -> bytes | None:
        try:
            return await self.redis.get(key)
        except RedisError as error:
            log.debug("RAG cache read unavailable (%s)", type(error).__name__)
            return None

    async def set(self, key: str, evidence: bytes) -> None:
        try:
            await self.redis.set(key, evidence, ex=self.ttl_seconds)
        except RedisError as error:
            log.debug("RAG cache write unavailable (%s)", type(error).__name__)
