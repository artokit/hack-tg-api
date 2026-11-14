from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config import AuthSettings
from repositories.employees import EmployeeRepository
from repositories.health import HealthRepository
from repositories.users import UserRepository
from repositories.tickets import TicketRepository
from services.auth import AuthService
from services.employees import EmployeeService
from services.health import HealthService
from services.ticket_service import TicketService

bearer_scheme = HTTPBearer(scheme_name="UserJWT", bearerFormat="JWT", auto_error=False)


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
