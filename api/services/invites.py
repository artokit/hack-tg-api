from uuid import UUID

from config import InviteSettings
from repositories.invites import InviteRepository
from schemas.employees import EmployeeCreate
from schemas.invites import InviteAccept, InviteCreate
from services.employees import EmployeeService


class InviteService:
    def __init__(
        self,
        repository: InviteRepository,
        employee_service: EmployeeService,
        settings: InviteSettings,
    ):
        self._repository = repository
        self._employee_service = employee_service
        self._settings = settings

    async def create(self, data: InviteCreate):
        if self._settings.telegram_bot_username is None:
            raise RuntimeError("TELEGRAM_BOT_USERNAME is not configured")
        invite = await self._repository.create(
            data.count_of_use, data.first_name, data.last_name
        )
        return {
            "id": invite.id,
            "count_of_use": invite.count_of_use,
            "first_name": invite.first_name,
            "last_name": invite.last_name,
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
        items = await self._repository.get_all((page - 1) * page_size, page_size)
        total = await self._repository.count()
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
        invite = await self.get_by_id(invite_id)
        employee = await self._employee_service.create(
            EmployeeCreate(
                telegram_id=data.telegram_id,
                first_name=(
                    invite.first_name if invite.first_name is not None else data.first_name
                ),
                last_name=(
                    invite.last_name if invite.last_name is not None else data.last_name
                ),
            ),
            username=data.username,
        )
        await self._repository.consume(invite)
        return employee
