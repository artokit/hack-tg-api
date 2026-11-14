from collections.abc import AsyncIterator
from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config import AuthSettings, InviteSettings
from repositories.employees import EmployeeRepository
from repositories.health import HealthRepository
from repositories.invites import InviteRepository
from repositories.tickets import TicketRepository
from repositories.users import UserRepository
from services.auth import AuthService
from services.employees import EmployeeService
from services.health import HealthService
from services.invites import InviteService
from services.rag import RagService
from services.ticket_service import TicketService

bearer_scheme = HTTPBearer(scheme_name="UserJWT", bearerFormat="JWT", auto_error=False)
bot_token_scheme = APIKeyHeader(name="X-Bot-Token", scheme_name="BotToken", auto_error=False)
rag_bearer_scheme = HTTPBearer(scheme_name="RagServiceToken", auto_error=False)


def get_rag_service(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(rag_bearer_scheme),
) -> RagService:
    if request.app.state.rag_service is None:
        raise HTTPException(status_code=503, detail="RAG disabled")
    token = request.app.state.rag_settings.rag_service_token.get_secret_value()
    if credentials is None or not compare_digest(credentials.credentials.encode(), token.encode()):
        raise HTTPException(
            status_code=401, detail="Invalid RAG service token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return request.app.state.rag_service


async def get_async_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


def get_auth_settings(request: Request) -> AuthSettings:
    return request.app.state.auth_settings


def get_auth_service(
    session: AsyncSession = Depends(get_async_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> AuthService:
    return AuthService(UserRepository(session), settings)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    service: AuthService = Depends(get_auth_service),
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await service.get_current_user(credentials.credentials)
    except PermissionError as error:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def get_health_service(session: AsyncSession = Depends(get_async_session)) -> HealthService:
    return HealthService(HealthRepository(session))


def get_employee_service(
    session: AsyncSession = Depends(get_async_session),
) -> EmployeeService:
    return EmployeeService(EmployeeRepository(session))


def get_ticket_service(
    session: AsyncSession = Depends(get_async_session),
) -> TicketService:
    return TicketService(TicketRepository(session))


def get_invite_settings(request: Request) -> InviteSettings:
    return request.app.state.invite_settings


def require_bot_token(
    token: str | None = Depends(bot_token_scheme),
    settings: InviteSettings = Depends(get_invite_settings),
) -> None:
    if (
        token is None
        or settings.bot_api_token is None
        or not compare_digest(
            token.encode("utf-8"),
            settings.bot_api_token.get_secret_value().encode("utf-8"),
        )
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing bot token")


def get_invite_service(
    session: AsyncSession = Depends(get_async_session),
    employee_service: EmployeeService = Depends(get_employee_service),
    settings: InviteSettings = Depends(get_invite_settings),
) -> InviteService:
    return InviteService(InviteRepository(session), employee_service, settings)
