from typing import Union

from config import settings
from http_client import ApiError, HttpClient
from models.users import User


class UserService:
    def __init__(self):
        self._http = HttpClient(settings.API_URL)

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> Union[User, None]:
        result = await self._http.get(f"/users/by-telegram-id/{telegram_user_id}", User)
        if result.status_code == 404:
            return None
        if not result.is_success:
            raise ApiError(f"GET /users/by-telegram-id/{telegram_user_id} -> {result.status_code}")
        return result.data

    async def create_user(self, telegram_user_id: int, username: Union[str, None]) -> Union[User, None]:
        result = await self._http.post(
            "/users",
            User,
            json={"telegram_user_id": telegram_user_id, "username": username},
        )
        if result.status_code == 409:
            return None
        if not result.is_success:
            raise ApiError(f"POST /users -> {result.status_code}")
        return result.data

    async def get_user_by_id(self, user_id: int) -> Union[User, None]:
        result = await self._http.get(f"/users/{user_id}", User)
        if result.status_code == 404:
            return None
        if not result.is_success:
            raise ApiError(f"GET /users/{user_id} -> {result.status_code}")
        return result.data


user_service = UserService()
