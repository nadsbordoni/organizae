from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.exceptions import (
    AuthConfigurationError,
    AuthError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
)
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    if isinstance(exc, (InvalidCredentialsError, InvalidAccessTokenError)):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )
    detail = (
        "Authentication is unavailable"
        if isinstance(exc, AuthConfigurationError)
        else "Internal server error"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": detail}
    )


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    token = service.login(login_data)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return token
