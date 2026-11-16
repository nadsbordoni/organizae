from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.users.exceptions import (
    InvalidUserDataError,
    UserConflictError,
    UserError,
)
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserResponse
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


def get_user_service(session: Annotated[Session, Depends(get_db)]) -> UserService:
    return UserService(session)


async def user_error_handler(request: Request, exc: UserError) -> JSONResponse:
    status_codes = {
        UserConflictError: status.HTTP_409_CONFLICT,
        InvalidUserDataError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    status_code = next(
        (
            code
            for error_type, code in status_codes.items()
            if isinstance(exc, error_type)
        ),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    detail = (
        str(exc)
        if status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
        else "Internal server error"
    )
    return JSONResponse(status_code=status_code, content={"detail": detail})


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_data: UserCreate,
    service: Annotated[UserService, Depends(get_user_service)],
) -> User:
    return service.create(user_data)
