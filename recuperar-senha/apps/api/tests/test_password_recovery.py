from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_service_repository import session

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.core.config import Settings
    from app.main import app
    from app.modules.password_recovery.route import get_password_recovery_service

from app.modules.password_recovery.messages import recovery_message
from app.modules.password_recovery.models import PasswordResetToken
from app.modules.password_recovery.repository import PasswordResetTokenRepository
from app.modules.password_recovery.schemas import (
    PasswordRecoveryRequest,
    PasswordRecoveryResponse,
)
from app.modules.password_recovery.service import (
    REQUEST_COOLDOWN,
    TOKEN_TTL,
    PasswordRecoveryService,
    RecoveryEmail,
    hash_token,
)
from app.modules.users.models import User

__all__ = ["session"]

RESET_URL = "https://organizae.example/painel/senha/redefinir"
path = "/api/v1/auth/password-recovery"
now = datetime(2026, 11, 30, 12, 0, tzinfo=UTC)
second = timedelta(seconds=1)


def token_in(message: RecoveryEmail) -> str:
    link = next(word for word in message.body.split() if word.startswith(RESET_URL))
    return parse_qs(urlsplit(link).query)["token"][0]


def stored(session: Session) -> list[PasswordResetToken]:
    statement = select(PasswordResetToken).order_by(PasswordResetToken.created_at)
    return list(session.scalars(statement).all())


def utc(value: datetime) -> datetime:
    # SQLite gives back naive datetimes; the tests only write UTC.
    return value.replace(tzinfo=UTC)


def new_user(session: Session, email: str = "ana@example.com") -> User:
    user = User(name="Ana Souza", email=email, password_hash="hash")
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def user(session: Session) -> User:
    return new_user(session)


@pytest.fixture
def service(session: Session) -> PasswordRecoveryService:
    return PasswordRecoveryService(session, RESET_URL)


# --- the request (service, SQLite created from the metadata) ---


def test_registered_email_receives_the_instructions(
    service: PasswordRecoveryService, user: User
) -> None:
    message = service.request("ana@example.com", now=now)

    assert message.to == "ana@example.com"
    assert message.subject == "Recuperação de senha - Organizaê"
    assert "Olá, Ana!" in message.body
    assert "30 minutos" in message.body
    assert len(token_in(message)) >= 40


def test_only_the_hash_of_the_token_is_stored(
    service: PasswordRecoveryService, session: Session, user: User
) -> None:
    message = service.request("ana@example.com", now=now)
    token = token_in(message)

    [row] = stored(session)
    assert row.user_id == user.id
    assert row.token_hash == hash_token(token)
    assert utc(row.expires_at) == now + TOKEN_TTL
    assert row.used_at is None
    raw_rows = session.execute(text("SELECT * FROM password_reset_tokens")).all()
    assert not any(token in str(value) for raw in raw_rows for value in raw)


def test_each_request_gets_a_different_token(
    service: PasswordRecoveryService, user: User
) -> None:
    first = service.request("ana@example.com", now=now)
    later = now + REQUEST_COOLDOWN + second
    assert token_in(first) != token_in(service.request("ana@example.com", now=later))


def test_email_is_matched_ignoring_case_and_spaces(
    service: PasswordRecoveryService, user: User
) -> None:
    assert service.request("  ANA@Example.com ", now=now) is not None


def test_unknown_email_gets_nothing_and_writes_nothing(
    service: PasswordRecoveryService, session: Session, user: User
) -> None:
    assert service.request("ninguem@example.com", now=now) is None
    assert stored(session) == []


def test_inactive_user_gets_nothing_and_writes_nothing(
    service: PasswordRecoveryService, session: Session, user: User
) -> None:
    user.is_active = False
    session.flush()

    assert service.request("ana@example.com", now=now) is None
    assert stored(session) == []


def test_recovery_is_off_without_a_reset_url(session: Session, user: User) -> None:
    service = PasswordRecoveryService(session, "")

    assert service.request("ana@example.com", now=now) is None
    assert stored(session) == []


def test_requests_inside_the_cooldown_are_ignored(
    service: PasswordRecoveryService, session: Session, user: User
) -> None:
    assert service.request("ana@example.com", now=now) is not None

    assert service.request("ana@example.com", now=now + REQUEST_COOLDOWN - second) is None
    assert len(stored(session)) == 1


def test_a_request_after_the_cooldown_replaces_the_previous_link(
    service: PasswordRecoveryService, session: Session, user: User
) -> None:
    service.request("ana@example.com", now=now)
    later = now + REQUEST_COOLDOWN + second

    assert service.request("ana@example.com", now=later) is not None

    first, newest = stored(session)
    assert utc(first.used_at) == later
    assert newest.used_at is None


def test_a_new_request_does_not_touch_tokens_of_other_users(
    service: PasswordRecoveryService, session: Session, user: User
) -> None:
    other = new_user(session, "bia@example.com")
    service.request("bia@example.com", now=now)
    service.request("ana@example.com", now=now)
    service.request("ana@example.com", now=now + REQUEST_COOLDOWN + second)

    others = [row for row in stored(session) if row.user_id == other.id]
    assert len(others) == 1
    assert others[0].used_at is None


def test_failure_while_saving_leaves_no_token(
    service: PasswordRecoveryService, session: Session, user: User
) -> None:
    service.token_repository.create = Mock(side_effect=RuntimeError("database down"))

    with pytest.raises(RuntimeError):
        service.request("ana@example.com", now=now)

    assert stored(session) == []


# --- the table ---


def test_token_hash_is_unique(session: Session, user: User) -> None:
    repository = PasswordResetTokenRepository(session)
    repository.create(
        PasswordResetToken(
            user_id=user.id, token_hash="a" * 64, expires_at=now, created_at=now
        )
    )
    with pytest.raises(IntegrityError):
        repository.create(
            PasswordResetToken(
                user_id=user.id, token_hash="a" * 64, expires_at=now, created_at=now
            )
        )


def test_tokens_disappear_with_their_user(session: Session, user: User) -> None:
    PasswordResetTokenRepository(session).create(
        PasswordResetToken(
            user_id=user.id, token_hash="b" * 64, expires_at=now, created_at=now
        )
    )

    session.delete(user)
    session.flush()

    assert stored(session) == []


# --- the e-mail and the input ---


def test_message_has_the_link_the_validity_and_a_warning() -> None:
    subject, body = recovery_message(
        name="Ana Souza", link=f"{RESET_URL}?token=abc", valid_for=timedelta(minutes=30)
    )

    assert subject == "Recuperação de senha - Organizaê"
    assert "Olá, Ana!" in body
    assert f"{RESET_URL}?token=abc" in body
    assert "30 minutos" in body
    assert "Se você não fez esse pedido, ignore este e-mail" in body


@pytest.mark.parametrize("email", ["ana", "ana@", "@example.com", "", "a b@example.com"])
def test_request_rejects_invalid_emails(email: str) -> None:
    with pytest.raises(ValidationError):
        PasswordRecoveryRequest(email=email)


def test_request_rejects_emails_longer_than_the_column() -> None:
    with pytest.raises(ValidationError):
        PasswordRecoveryRequest(email="a" * 250 + "@example.com")


def test_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PasswordRecoveryRequest(email="ana@example.com", user_id="x")


def test_recovery_is_off_by_default() -> None:
    assert Settings.model_fields["PASSWORD_RESET_URL"].default == ""


# --- HTTP ---


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, Mock, Mock]]:
    recovery_service = Mock(spec=PasswordRecoveryService)
    recovery_service.request.return_value = None
    app.dependency_overrides[get_password_recovery_service] = lambda: recovery_service
    try:
        with (
            patch("app.modules.password_recovery.route.send_email") as send_email,
            TestClient(app) as client,
        ):
            yield client, recovery_service, send_email
    finally:
        app.dependency_overrides.pop(get_password_recovery_service, None)


EMAIL = RecoveryEmail("ana@example.com", "Recuperação de senha", "link com SECRET-TOKEN")


def test_registered_email_gets_202_and_the_email_is_sent(
    api_client: tuple[TestClient, Mock, Mock],
) -> None:
    client, recovery_service, send_email = api_client
    recovery_service.request.return_value = EMAIL

    response = client.post(path, json={"email": "ana@example.com"})

    assert response.status_code == 202
    assert response.json() == PasswordRecoveryResponse().model_dump()
    recovery_service.request.assert_called_once_with("ana@example.com")
    send_email.assert_called_once_with(EMAIL.to, EMAIL.subject, EMAIL.body)


def test_unknown_email_gets_the_same_answer_and_no_email(
    api_client: tuple[TestClient, Mock, Mock],
) -> None:
    client, recovery_service, send_email = api_client
    recovery_service.request.return_value = None

    response = client.post(path, json={"email": "ninguem@example.com"})

    assert response.status_code == 202
    assert response.json() == PasswordRecoveryResponse().model_dump()
    send_email.assert_not_called()


def test_answer_does_not_reveal_whether_the_email_exists(
    api_client: tuple[TestClient, Mock, Mock],
) -> None:
    client, recovery_service, _ = api_client
    answers = []
    for message in (EMAIL, None):
        recovery_service.request.return_value = message
        response = client.post(path, json={"email": "ana@example.com"})
        answers.append((response.status_code, response.text, response.headers))

    assert answers[0] == answers[1]


def test_token_never_goes_back_to_the_client(
    api_client: tuple[TestClient, Mock, Mock],
) -> None:
    client, recovery_service, _ = api_client
    recovery_service.request.return_value = EMAIL

    response = client.post(path, json={"email": "ana@example.com"})

    assert "SECRET-TOKEN" not in response.text
    assert "SECRET-TOKEN" not in str(response.headers)


def test_mail_failure_does_not_change_the_answer(
    api_client: tuple[TestClient, Mock, Mock],
) -> None:
    client, recovery_service, send_email = api_client
    recovery_service.request.return_value = EMAIL
    send_email.return_value = False

    response = client.post(path, json={"email": "ana@example.com"})

    assert response.status_code == 202
    assert response.json() == PasswordRecoveryResponse().model_dump()


@pytest.mark.parametrize(
    "body",
    [
        {"email": "ana"},
        {"email": ""},
        {},
        {"email": "ana@example.com", "password": "x"},
    ],
)
def test_invalid_requests_are_a_422_and_do_nothing(
    api_client: tuple[TestClient, Mock, Mock], body: dict[str, str]
) -> None:
    client, recovery_service, send_email = api_client

    assert client.post(path, json=body).status_code == 422
    recovery_service.request.assert_not_called()
    send_email.assert_not_called()


def test_the_reset_page_comes_from_the_settings() -> None:
    with patch("app.modules.password_recovery.route.settings") as settings:
        settings.PASSWORD_RESET_URL = RESET_URL
        built = get_password_recovery_service(Mock(spec=Session))

    assert built.reset_url == RESET_URL


# --- migration ---


def test_migration_creates_the_token_table() -> None:
    from io import StringIO
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("d2f6a8c41b73")
    assert revision.revision in {
        item.revision for item in script.iterate_revisions("head", "base")
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE password_reset_tokens" in sql
    assert "uq_password_reset_tokens_hash" in sql
    assert "ON DELETE CASCADE" in sql
    assert "ix_password_reset_tokens_user_created" in sql
