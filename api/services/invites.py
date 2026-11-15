from datetime import UTC, datetime, timedelta
from uuid import UUID

from config import InviteSettings
from repositories.invites import InviteRepository
from schemas.invites import InviteAccept, InviteCreate


class InviteExpiredError(Exception):
    pass


class InviteService:
    def __init__(
        self,
        repository: InviteRepository,
        settings: InviteSettings,
    ):
        self._repository = repository
        self._settings = settings

    async def create(self, data: InviteCreate):
        if self._settings.telegram_bot_username is None:
            raise RuntimeError("TELEGRAM_BOT_USERNAME is not configured")
        expires_at = datetime.now(UTC) + timedelta(minutes=data.expires_in_minutes)
        invite = await self._repository.create(
            data.count_of_use, data.first_name, data.last_name, expires_at
        )
        return {
            "id": invite.id,
            "count_of_use": invite.count_of_use,
            "first_name": invite.first_name,
            "last_name": invite.last_name,
            "expires_at": invite.expires_at,
            "link": (
                f"https://t.me/{self._settings.telegram_bot_username}"
                f"?start=invite_{invite.id}"
            ),
        }

    async def get_by_id(self, invite_id: UUID):
        invite = await self._repository.get_by_id(invite_id)
        if invite is None:
            raise LookupError("Invite not found")
        return invite

    async def get_all(self, page: int, page_size: int):
        items, total = await self._repository.get_active_page(
            (page - 1) * page_size, page_size, datetime.now(UTC)
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def delete(self, invite_id: UUID) -> None:
        invite = await self.get_by_id(invite_id)
        await self._repository.delete(invite)

    async def accept(self, invite_id: UUID, data: InviteAccept):
        invite = await self._repository.lock_for_accept(invite_id)
        if invite is None:
            raise LookupError("Invite not found")
        if invite.expires_at is not None and invite.expires_at <= datetime.now(UTC):
            raise InviteExpiredError
        return await self._repository.accept(
            invite,
            data.telegram_id,
            data.username,
            invite.first_name if invite.first_name is not None else data.first_name,
            invite.last_name if invite.last_name is not None else data.last_name,
        )
