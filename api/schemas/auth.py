from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=72)


class TokenRead(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
