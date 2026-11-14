from asyncio import to_thread

from config import AuthSettings
from repositories.users import UserRepository
from schemas.auth import LoginRequest
from utils.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    get_token_user_id,
    verify_password,
)


class AuthService:
    def __init__(self, repository: UserRepository, settings: AuthSettings):
        self._repository = repository
        self._settings = settings

    async def login(self, data: LoginRequest) -> str:
        user = await self._repository.get_by_email(data.email.strip().casefold())
        hashed_password = user.hashed_password if user is not None else DUMMY_PASSWORD_HASH
        valid_password = await to_thread(
            verify_password, data.password.get_secret_value(), hashed_password
        )
        if user is None or not valid_password:
            raise PermissionError("Invalid email or password")
        return create_access_token(
            user.id,
            self._settings.jwt_secret.get_secret_value(),
            self._settings.jwt_access_token_expire_minutes,
        )

    async def get_current_user(self, token: str):
        user_id = get_token_user_id(token, self._settings.jwt_secret.get_secret_value())
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise PermissionError("Invalid or expired access token")
        return user
