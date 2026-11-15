from math import ceil

from redis.asyncio import Redis
from redis.exceptions import RedisError

from models.bans import BanState
from utils.exceptions import BanUnavailableError


class BanRepository:
    _create_script = """
local ttl = redis.call('PTTL', KEYS[1])
if ttl > 0 then
    return {tonumber(redis.call('GET', KEYS[1])), math.ceil(ttl / 1000), redis.call('PEXPIRETIME', KEYS[1])}
end
local level = math.min(tonumber(redis.call('GET', KEYS[2]) or '0') + 1, #ARGV)
redis.call('SET', KEYS[2], level)
redis.call('SET', KEYS[1], level, 'EX', ARGV[level])
return {level, tonumber(ARGV[level]), redis.call('PEXPIRETIME', KEYS[1])}
"""

    def __init__(self, redis: Redis):
        self._redis = redis

    def _key(self, telegram_id: int) -> str:
        return f"bans:telegram:{{{telegram_id}}}"

    async def create(self, telegram_id: int, durations: tuple[int, ...]) -> BanState:
        key = self._key(telegram_id)
        try:
            level, seconds, expires_at_ms = await self._redis.eval(
                self._create_script, 2, f"{key}:active", f"{key}:level", *durations,
            )
        except RedisError as error:
            raise BanUnavailableError("Ban storage unavailable") from error
        return BanState(ban_level=int(level), retry_after_seconds=int(seconds), expires_at_ms=int(expires_at_ms))

    async def remaining(self, telegram_id: int) -> int:
        try:
            milliseconds = await self._redis.pttl(f"{self._key(telegram_id)}:active")
        except RedisError as error:
            raise BanUnavailableError("Ban storage unavailable") from error
        if milliseconds == -1:
            raise BanUnavailableError("Ban expiration is missing")
        return max(0, ceil(milliseconds / 1000))
