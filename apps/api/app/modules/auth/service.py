from secrets import token_urlsafe

from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.modules.auth.exceptions import InvalidAccessTokenError, InvalidCredentialsError
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

# Unknown accounts still perform password verification to reduce timing differences.
_dummy_password_hash = hash_password(token_urlsafe(32))


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def authenticate(self, login_data: LoginRequest) -> User:
        email = str(login_data.email).strip().lower()
        user = self.repository.get_by_email(email)
        password_hash = user.password_hash if user is not None else _dummy_password_hash
        password_valid = verify_password(
            login_data.password.get_secret_value(), password_hash
        )
        if user is None or not password_valid or not user.is_active:
            raise InvalidCredentialsError("Invalid email or password")
        return user

    def login(self, login_data: LoginRequest) -> TokenResponse:
        user = self.authenticate(login_data)
        return TokenResponse(access_token=create_access_token(user.id))

    def get_current_user(self, token: str) -> User:
        payload = decode_access_token(token)
        user = self.repository.get_by_id(payload.sub)
        if user is None or not user.is_active:
            raise InvalidAccessTokenError("Could not validate credentials")
        return user
