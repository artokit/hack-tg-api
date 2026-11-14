from asyncio import to_thread

from config import AuthSettings
from repositories.admins import AdminRepository
from schemas.auth import LoginRequest
from utils.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    get_token_admin_id,
    verify_password,
)


class AuthService:
    def __init__(self, repository: AdminRepository, settings: AuthSettings):
        self._repository = repository
        self._settings = settings

    async def login(self, data: LoginRequest) -> str:
        admin = await self._repository.get_by_email(data.email.strip().casefold())
        hashed_password = admin.hashed_password if admin is not None else DUMMY_PASSWORD_HASH
        valid_password = await to_thread(
            verify_password, data.password.get_secret_value(), hashed_password
        )
        if admin is None or not valid_password:
            raise PermissionError("Invalid email or password")
        return create_access_token(
            admin.id,
            self._settings.jwt_secret.get_secret_value(),
            self._settings.jwt_access_token_expire_minutes,
        )

    async def get_current_admin(self, token: str):
        admin_id = get_token_admin_id(token, self._settings.jwt_secret.get_secret_value())
        admin = await self._repository.get_by_id(admin_id)
        if admin is None:
            raise PermissionError("Invalid or expired access token")
        return admin
