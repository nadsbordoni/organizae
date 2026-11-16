from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.modules.auth.service import AuthService

from app.modules.auth.exceptions import (
    AuthConfigurationError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
)
from app.modules.auth.schemas import LoginRequest, TokenPayload
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


@pytest.fixture
def login_data() -> LoginRequest:
    return LoginRequest(email="USER@EXAMPLE.COM", password=" test-only-password ")


@pytest.fixture
def user() -> Mock:
    return Mock(spec=User, id=uuid4(), password_hash="encoded-password", is_active=True)


@pytest.fixture
def password_verifier(monkeypatch: pytest.MonkeyPatch) -> Mock:
    verifier = Mock(return_value=True)
    monkeypatch.setattr("app.modules.auth.service.verify_password", verifier)
    return verifier


@pytest.fixture
def service(user: Mock, password_verifier: Mock) -> AuthService:
    service = AuthService(Mock(spec=Session))
    service.repository = Mock(spec=UserRepository)
    service.repository.get_by_email.return_value = user
    service.repository.get_by_id.return_value = user
    return service


def test_authenticate_normalizes_email_and_preserves_password(
    service: AuthService, login_data: LoginRequest, user: Mock, password_verifier: Mock
) -> None:
    assert service.authenticate(login_data) is user
    service.repository.get_by_email.assert_called_once_with("user@example.com")
    password_verifier.assert_called_once_with(
        " test-only-password ", user.password_hash
    )
    service.session.commit.assert_not_called()
    service.session.rollback.assert_not_called()


@pytest.mark.parametrize("failure", ["unknown_email", "wrong_password", "inactive"])
def test_failed_authentication_uses_same_message_and_performs_verification(
    service: AuthService,
    login_data: LoginRequest,
    user: Mock,
    password_verifier: Mock,
    failure: str,
) -> None:
    if failure == "unknown_email":
        service.repository.get_by_email.return_value = None
    elif failure == "wrong_password":
        password_verifier.return_value = False
    else:
        user.is_active = False
    with pytest.raises(InvalidCredentialsError, match="^Invalid email or password$"):
        service.authenticate(login_data)
    password_verifier.assert_called_once()
    if failure == "unknown_email":
        assert password_verifier.call_args.args[1].startswith("$argon2id$")
    service.session.commit.assert_not_called()


def test_login_issues_token_only_for_authenticated_user(
    service: AuthService,
    login_data: LoginRequest,
    user: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_token = Mock(return_value="access-token")
    monkeypatch.setattr("app.modules.auth.service.create_access_token", create_token)
    response = service.login(login_data)
    create_token.assert_called_once_with(user.id)
    assert response.model_dump() == {
        "access_token": "access-token",
        "token_type": "bearer",
    }
    service.session.commit.assert_not_called()


def test_failed_login_never_issues_token(
    service: AuthService,
    login_data: LoginRequest,
    password_verifier: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_verifier.return_value = False
    create_token = Mock()
    monkeypatch.setattr("app.modules.auth.service.create_access_token", create_token)
    with pytest.raises(InvalidCredentialsError):
        service.login(login_data)
    create_token.assert_not_called()


def test_current_user_is_loaded_from_verified_subject(
    service: AuthService, user: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = TokenPayload(sub=user.id, iat=100, exp=200, token_type="access")
    decoder = Mock(return_value=payload)
    monkeypatch.setattr("app.modules.auth.service.decode_access_token", decoder)
    assert service.get_current_user("token") is user
    decoder.assert_called_once_with("token")
    service.repository.get_by_id.assert_called_once_with(user.id)


@pytest.mark.parametrize("inactive", [False, True])
def test_current_user_rejects_removed_or_inactive_accounts(
    service: AuthService, user: Mock, monkeypatch: pytest.MonkeyPatch, inactive: bool
) -> None:
    monkeypatch.setattr(
        "app.modules.auth.service.decode_access_token",
        Mock(
            return_value=TokenPayload(
                sub=user.id, iat=100, exp=200, token_type="access"
            )
        ),
    )
    if inactive:
        user.is_active = False
    else:
        service.repository.get_by_id.return_value = None
    with pytest.raises(InvalidAccessTokenError):
        service.get_current_user("token")


@pytest.mark.parametrize(
    "error_type", [InvalidAccessTokenError, AuthConfigurationError]
)
def test_decode_errors_propagate_before_user_lookup(
    service: AuthService, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    error = error_type("failure")
    monkeypatch.setattr(
        "app.modules.auth.service.decode_access_token", Mock(side_effect=error)
    )
    with pytest.raises(error_type) as caught:
        service.get_current_user("token")
    assert caught.value is error
    service.repository.get_by_id.assert_not_called()


def test_database_failure_is_not_disguised_as_invalid_credentials(
    service: AuthService, login_data: LoginRequest
) -> None:
    error = OperationalError("statement", {}, Exception("connection failed"))
    service.repository.get_by_email.side_effect = error
    with pytest.raises(OperationalError) as caught:
        service.login(login_data)
    assert caught.value is error


def test_login_preserves_token_configuration_errors(
    service: AuthService, login_data: LoginRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = AuthConfigurationError("JWT is not configured")
    monkeypatch.setattr(
        "app.modules.auth.service.create_access_token", Mock(side_effect=error)
    )
    with pytest.raises(AuthConfigurationError) as caught:
        service.login(login_data)
    assert caught.value is error
