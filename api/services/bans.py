from models.bans import BanState
from repositories.bans import BanRepository


class UserBannedError(Exception):
    def __init__(self, retry_after_seconds: int):
        super().__init__("User is banned")
        self.retry_after_seconds = retry_after_seconds


class BanService:
    durations = (180, 300, 600)

    def __init__(self, repository: BanRepository):
        self._repository = repository

    async def create(self, telegram_id: int) -> BanState:
        return await self._repository.create(telegram_id, self.durations)

    async def ensure_allowed(self, telegram_id: int) -> None:
        seconds = await self._repository.remaining(telegram_id)
        if seconds > 0:
            raise UserBannedError(seconds)
