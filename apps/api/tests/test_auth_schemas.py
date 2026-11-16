from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import LoginRequest, TokenPayload, TokenResponse


def test_login_hides_password_and_preserves_its_value() -> None:
    password = " test-only-password "
    request = LoginRequest(email="user@EXAMPLE.COM", password=password)
    assert request.email == "user@example.com"
    assert request.password.get_secret_value() == password
    assert password not in repr(request)
    assert password not in request.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "user@example.com"},
        {"password": "password"},
        {"email": "invalid", "password": "password"},
        {"email": "user@example.com", "password": ""},
        {"email": "user@example.com", "password": "a" * 129},
        {
            "email": "user@example.com",
            "password": "password",
            "business_id": str(uuid4()),
        },
    ],
)
def test_login_validates_credentials_and_rejects_extra_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(**payload)


def test_token_response_uses_bearer_and_does_not_log_token() -> None:
    response = TokenResponse(access_token="signed-token")
    assert response.model_dump() == {
        "access_token": "signed-token",
        "token_type": "bearer",
    }
    assert "signed-token" not in repr(response)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"access_token": ""},
        {"access_token": "token", "token_type": "refresh"},
        {"access_token": "token", "password": "password"},
    ],
)
def test_token_response_rejects_invalid_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TokenResponse(**payload)


def test_payload_parses_uuid_subject_and_serializes_to_jwt_claims() -> None:
    subject = uuid4()
    payload = TokenPayload(sub=str(subject), iat=100, exp=200, token_type="access")
    assert payload.sub == subject
    assert payload.model_dump(mode="json") == {
        "sub": str(subject),
        "iat": 100,
        "exp": 200,
        "token_type": "access",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"sub": "invalid"},
        {"sub": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"},
        {"iat": "100"},
        {"iat": True},
        {"iat": -1},
        {"exp": 100},
        {"exp": 99},
        {"exp": "200"},
        {"exp": 200.5},
        {"token_type": "refresh"},
        {"business_id": str(uuid4())},
    ],
)
def test_payload_enforces_claim_types_and_expiration_order(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TokenPayload(
            **{
                "sub": str(uuid4()),
                "iat": 100,
                "exp": 200,
                "token_type": "access",
                **change,
            }
        )
