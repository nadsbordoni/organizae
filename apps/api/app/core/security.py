from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError as JWTInvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pydantic import ValidationError

from app.core.config import settings
from app.modules.auth.exceptions import AuthConfigurationError, InvalidAccessTokenError
from app.modules.auth.schemas import TokenPayload

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password, password_hash)
    except UnknownHashError:
        return False


def create_access_token(subject: UUID) -> str:
    secret = _get_jwt_secret()
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = TokenPayload(
        sub=subject,
        iat=int(issued_at.timestamp()),
        exp=int(expires_at.timestamp()),
        token_type="access",
    )
    return jwt.encode(
        payload.model_dump(mode="json"), secret, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> TokenPayload:
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp", "token_type"]},
        )
        return TokenPayload.model_validate(payload)
    except (JWTInvalidTokenError, ValidationError):
        raise InvalidAccessTokenError("Invalid or expired access token") from None


def _get_jwt_secret() -> str:
    secret = settings.JWT_SECRET_KEY.get_secret_value()
    if not secret.strip() or len(secret.encode("utf-8")) < 32:
        raise AuthConfigurationError(
            "JWT_SECRET_KEY must be configured with at least 32 bytes"
        )
    return secret
