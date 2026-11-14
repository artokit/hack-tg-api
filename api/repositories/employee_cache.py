from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.exceptions import RedisError

from utils.exceptions import EmployeeCacheUnavailableError


class EmployeeCacheRepository:
    ttl_seconds = 180

    def __init__(self, redis: Redis):
        self._redis = redis

    def _key(self, telegram_id: int) -> str:
        return f"employees:telegram:{telegram_id}"

    async def get(self, telegram_id: int) -> str | None:
        try:
            return await self._redis.get(self._key(telegram_id))
        except RedisError as error:
            raise EmployeeCacheUnavailableError("Employee cache unavailable") from error

    async def set(self, telegram_id: int, data: str) -> None:
        try:
            await self._redis.set(self._key(telegram_id), data, ex=self.ttl_seconds)
        except RedisError as error:
            raise EmployeeCacheUnavailableError("Employee cache unavailable") from error

    async def delete(self, telegram_id: int) -> None:
        try:
            await self._redis.delete(self._key(telegram_id))
        except RedisError as error:
            raise EmployeeCacheUnavailableError("Employee cache unavailable") from error

    @asynccontextmanager
    async def lock(self, telegram_id: int) -> AsyncIterator[None]:
        try:
            async with self._redis.lock(
                f"{self._key(telegram_id)}:lock", timeout=30, blocking_timeout=5
            ):
                yield
        except RedisError as error:
            raise EmployeeCacheUnavailableError("Employee cache unavailable") from error
