from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.chat import ChatService
from services.users import UserService

bearer = HTTPBearer(auto_error=False)


def require_bot(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = request.app.state.agent_api_token
    if credentials is None or not compare_digest(
        credentials.credentials.encode(), expected
    ):
        raise HTTPException(
            401, "Invalid bot credentials", headers={"WWW-Authenticate": "Bearer"}
        )


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_user_service(request: Request) -> UserService:
    return request.app.state.user_service
