import base64
import json
import secrets
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr, ValidationError

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.core.config import Settings, settings
    from app.core.security import (
        create_access_token,
        decode_access_token,
        hash_password,
        verify_password,
    )

from app.modules.auth.exceptions import AuthConfigurationError, InvalidAccessTokenError


@pytest.fixture
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = secrets.token_urlsafe(64)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(secret))
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    return secret


@pytest.fixture
def claims() -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    return {
        "sub": str(uuid4()),
        "iat": now - 60,
        "exp": now + 1800,
        "token_type": "access",
    }


def test_password_verification_preserves_argon2_behavior() -> None:
    password = "test-only-password"
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$")
    assert verify_password(password, encoded) is True
    assert verify_password("wrong-password", encoded) is False


@pytest.mark.parametrize("encoded", ["", "not-a-hash", "$argon2id$invalid"])
def test_unrecognized_or_corrupt_hash_does_not_authenticate(encoded: str) -> None:
    assert verify_password("test-only-password", encoded) is False


def test_access_token_round_trip_and_required_claims(jwt_secret: str) -> None:
    subject = uuid4()
    before = int(datetime.now(UTC).timestamp())
    token = create_access_token(subject)
    after = int(datetime.now(UTC).timestamp())
    payload = decode_access_token(token)
    assert payload.sub == subject
    assert payload.token_type == "access"
    assert before <= payload.iat <= after
    assert payload.exp - payload.iat == 30 * 60
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    verified = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    assert set(verified) == {"sub", "iat", "exp", "token_type"}
    assert verified["sub"] == str(subject)


def test_configured_expiration_is_used(
    jwt_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 5)
    payload = decode_access_token(create_access_token(uuid4()))
    assert payload.exp - payload.iat == 5 * 60


@pytest.mark.parametrize("part", ["payload", "signature"])
def test_tampered_token_is_rejected(jwt_secret: str, part: str) -> None:
    token = create_access_token(uuid4())
    header, payload, signature = token.split(".")
    if part == "payload":
        replacement = json.dumps({"sub": str(uuid4())}).encode()
        payload = base64.urlsafe_b64encode(replacement).rstrip(b"=").decode()
    else:
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(f"{header}.{payload}.{signature}")


def test_token_signed_with_another_key_is_rejected(
    jwt_secret: str, claims: dict[str, object]
) -> None:
    token = jwt.encode(claims, secrets.token_urlsafe(64), algorithm="HS256")
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("algorithm", ["HS384", "none"])
def test_token_cannot_choose_its_own_algorithm(
    jwt_secret: str, claims: dict[str, object], algorithm: str
) -> None:
    token = jwt.encode(
        claims, jwt_secret if algorithm != "none" else "", algorithm=algorithm
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("field", ["sub", "iat", "exp", "token_type"])
def test_required_claims_cannot_be_omitted(
    jwt_secret: str, claims: dict[str, object], field: str
) -> None:
    claims.pop(field)
    token = jwt.encode(claims, jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize(
    "change",
    [
        {"sub": "invalid"},
        {"sub": 1},
        {"sub": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"},
        {"token_type": "refresh"},
        {"token_type": None},
        {"iat": "1"},
        {"iat": True},
        {"iat": 1.5},
        {"exp": "9999999999"},
        {"business_id": str(uuid4())},
    ],
)
def test_invalid_payload_claims_are_rejected(
    jwt_secret: str, claims: dict[str, object], change: dict[str, object]
) -> None:
    token = jwt.encode({**claims, **change}, jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("invalid_time", ["expired", "future_issue"])
def test_temporal_validation(
    jwt_secret: str, claims: dict[str, object], invalid_time: str
) -> None:
    now = int(datetime.now(UTC).timestamp())
    if invalid_time == "expired":
        claims["exp"] = now - 1
    else:
        claims["iat"] = now + 60
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(jwt.encode(claims, jwt_secret, algorithm="HS256"))


@pytest.mark.parametrize("token", ["", "invalid", "a.b.c"])
def test_malformed_tokens_have_a_generic_error(jwt_secret: str, token: str) -> None:
    with pytest.raises(
        InvalidAccessTokenError, match="^Invalid or expired access token$"
    ):
        decode_access_token(token)


@pytest.mark.parametrize("secret", ["", " " * 32, secrets.token_hex(8)])
@pytest.mark.parametrize("operation", ["create", "decode"])
def test_missing_or_short_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch, secret: str, operation: str
) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(secret))
    with pytest.raises(AuthConfigurationError, match="JWT_SECRET_KEY"):
        if operation == "create":
            create_access_token(uuid4())
        else:
            decode_access_token("invalid")


def test_password_hashing_does_not_require_jwt_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(""))
    encoded = hash_password("test-only-password")
    assert verify_password("test-only-password", encoded) is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"JWT_ALGORITHM": "none"},
        {"JWT_ALGORITHM": "HS512"},
        {"JWT_ACCESS_TOKEN_EXPIRE_MINUTES": 0},
        {"JWT_ACCESS_TOKEN_EXPIRE_MINUTES": -1},
    ],
)
def test_unsafe_jwt_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            DB_HOST="localhost",
            DB_NAME="test",
            DB_USER="test",
            DB_PASSWORD="test",
            **overrides,
        )
