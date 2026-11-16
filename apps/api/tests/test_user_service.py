from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory  # noqa: F401
from app.modules.businesses.models import Business  # noqa: F401
from app.modules.professionals.models import Professional  # noqa: F401
from app.modules.users.exceptions import InvalidUserDataError, UserConflictError
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserResponse
from app.modules.users.service import UserService


@pytest.fixture
def data() -> UserCreate:
    return UserCreate(
        name=" User ", email="USER@EXAMPLE.COM", password="test-only-password"
    )


@pytest.fixture
def password_hash_mock(monkeypatch: pytest.MonkeyPatch) -> Mock:
    hasher = Mock(return_value="encoded-password")
    monkeypatch.setattr("app.modules.users.service.hash_password", hasher)
    return hasher


@pytest.fixture
def service(password_hash_mock: Mock) -> UserService:
    service = UserService(Mock(spec=Session))
    service.repository = Mock(spec=UserRepository)
    service.repository.get_by_email.return_value = None
    return service


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    try:
        # Application databases use Alembic; these tables exist only in memory.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine, autoflush=False, expire_on_commit=True) as session:
            yield session
    finally:
        engine.dispose()


def test_password_hash_uses_argon2_and_random_salts() -> None:
    password = "test-only-password"
    first_hash = hash_password(password)
    second_hash = hash_password(password)
    assert first_hash.startswith("$argon2id$")
    assert first_hash != second_hash
    assert first_hash != password
    assert PasswordHash.recommended().verify(password, first_hash)


def test_create_normalizes_email_hashes_password_and_commits(
    service: UserService, data: UserCreate, password_hash_mock: Mock
) -> None:
    user = service.create(data)
    service.repository.get_by_email.assert_called_once_with("user@example.com")
    password_hash_mock.assert_called_once_with(data.password)
    service.repository.create.assert_called_once_with(
        name="User", email="user@example.com", password_hash="encoded-password"
    )
    assert user is service.repository.create.return_value
    service.session.commit.assert_called_once_with()
    service.session.refresh.assert_called_once_with(user)
    service.session.rollback.assert_not_called()


def test_duplicate_email_does_not_hash_or_write(
    service: UserService, data: UserCreate, password_hash_mock: Mock
) -> None:
    service.repository.get_by_email.return_value = Mock(spec=User)
    with pytest.raises(UserConflictError, match="already registered"):
        service.create(data)
    password_hash_mock.assert_not_called()
    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_overlong_email_does_not_query_or_write(service: UserService) -> None:
    data = UserCreate.model_construct(
        name="User", email="a" * 256, password="test-only-password"
    )
    with pytest.raises(InvalidUserDataError):
        service.create(data)
    service.repository.get_by_email.assert_not_called()
    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize("stage", ["lookup", "write", "commit", "refresh"])
@pytest.mark.parametrize("error_type", [IntegrityError, OperationalError, RuntimeError])
def test_failures_roll_back_without_hiding_unexpected_errors(
    service: UserService, data: UserCreate, stage: str, error_type: type[Exception]
) -> None:
    error = (
        error_type("sensitive SQL", {}, Exception("internal details"))
        if error_type is not RuntimeError
        else RuntimeError("unexpected failure")
    )
    target = {
        "lookup": service.repository.get_by_email,
        "write": service.repository.create,
        "commit": service.session.commit,
        "refresh": service.session.refresh,
    }[stage]
    target.side_effect = error
    expected = UserConflictError if error_type is IntegrityError else error_type
    with pytest.raises(expected) as caught:
        service.create(data)
    service.session.rollback.assert_called_once_with()
    if error_type is IntegrityError:
        assert "sensitive SQL" not in str(caught.value)
        assert "internal details" not in str(caught.value)
    else:
        assert caught.value is error
    if stage in ("lookup", "write"):
        service.session.commit.assert_not_called()


def test_hashing_failure_prevents_write_and_rolls_back(
    service: UserService, data: UserCreate, password_hash_mock: Mock
) -> None:
    password_hash_mock.side_effect = RuntimeError("hashing failed")
    with pytest.raises(RuntimeError, match="hashing failed"):
        service.create(data)
    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_real_user_can_be_serialized_after_session_closes(
    session: Session, data: UserCreate
) -> None:
    user = UserService(session).create(data)
    assert user.id.version == 4
    assert user.is_active is True
    assert user.business_id is None
    assert PasswordHash.recommended().verify(data.password, user.password_hash)
    session.close()
    response = UserResponse.model_validate(user).model_dump(mode="json")
    assert response["email"] == "user@example.com"
    assert "password_hash" not in response
    assert "password" not in response


def test_real_duplicate_email_is_case_insensitive(
    session: Session, data: UserCreate
) -> None:
    service = UserService(session)
    identifier = service.create(data).id
    with pytest.raises(UserConflictError):
        service.create(
            UserCreate(name="Other", email="user@example.com", password=data.password)
        )
    assert [user.id for user in session.scalars(select(User)).all()] == [identifier]


def test_database_unique_constraint_handles_duplicate_after_precheck(
    session: Session, data: UserCreate, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = UserService(session)
    identifier = service.create(data).id
    monkeypatch.setattr(service.repository, "get_by_email", Mock(return_value=None))
    with pytest.raises(UserConflictError):
        service.create(data)
    assert [user.id for user in session.scalars(select(User)).all()] == [identifier]


def test_real_rollback_removes_flushed_user(
    session: Session, data: UserCreate, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = UserService(session)
    original = service.repository.create

    def fail_after_flush(**fields: object) -> User:
        original(**fields)
        raise RuntimeError("after flush")

    monkeypatch.setattr(service.repository, "create", fail_after_flush)
    with pytest.raises(RuntimeError, match="after flush"):
        service.create(data)
    assert session.scalars(select(User)).all() == []
