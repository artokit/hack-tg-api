from typing import Union

from models.users import User

class UserService:
    async def get_user_by_id(self, telegram_user_id: int) -> Union[User, None]:
        pass


service = UserService()
