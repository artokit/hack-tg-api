from fastapi import APIRouter, Depends, HTTPException

from depends import get_auth_service
from schemas.auth import LoginRequest, TokenRead
from services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenRead)
async def login(
    data: LoginRequest,
    service: AuthService = Depends(get_auth_service),
):
    try:
        access_token = await service.login(data)
    except PermissionError as error:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    return TokenRead(access_token=access_token)
