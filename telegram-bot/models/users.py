from typing import Union

from pydantic import BaseModel


class User(BaseModel):
    id: int
    telegram_user_id: int
    username: Union[str, None] = None
