from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.exceptions import AuthConfigurationError, InvalidAccessTokenError
from app.modules.auth.service import AuthService
from app.modules.users.models import User

bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


def get_auth_service(session: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(session)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_error
    try:
        return service.get_current_user(credentials.credentials)
    except InvalidAccessTokenError:
        raise credentials_error from None
    except AuthConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is unavailable",
        ) from None


def get_current_business_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    if current_user.business_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have a business",
        )
    return current_user.business_id


def get_owned_business_id(
    business_id: UUID4,
    current_business_id: Annotated[UUID, Depends(get_current_business_id)],
) -> UUID:
    if business_id != current_business_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Business not found"
        )
    return current_business_id
