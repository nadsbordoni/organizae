from collections.abc import Iterator
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.db.session import get_db
    from app.main import app
    from app.modules.users.route import get_user_service

from app.db.base import Base
from app.modules.users.exceptions import (
    InvalidUserDataError,
    UserConflictError,
    UserError,
)
from app.modules.users.models import User
from app.modules.users.service import UserService


@pytest.fixture
def database() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        # Never connect to application databases in HTTP integration tests.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def client(database: Engine) -> Iterator[TestClient]:
    def get_test_db() -> Iterator[Session]:
        with Session(database, autoflush=False, expire_on_commit=True) as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db)


@pytest.fixture
def payload() -> dict[str, str]:
    return {
        "name": " User ",
        "email": "USER@EXAMPLE.COM",
        "password": "test-only-password",
    }


def test_public_registration_is_registered_and_persists_safe_data(
    client: TestClient, database: Engine, payload: dict[str, str]
) -> None:
    response = client.post("/api/v1/users", json=payload)
    assert response.status_code == 201
    result = response.json()
    assert set(result) == {"id", "name", "email", "is_active", "business_id"}
    assert result["name"] == "User"
    assert result["email"] == "user@example.com"
    assert result["is_active"] is True
    assert result["business_id"] is None
    with Session(database) as session:
        stored = session.scalar(select(User))
        assert str(stored.id) == result["id"]
        assert stored.password_hash != payload["password"]
        assert PasswordHash.recommended().verify(
            payload["password"], stored.password_hash
        )


def test_duplicate_email_returns_conflict_without_extra_user(
    client: TestClient, database: Engine, payload: dict[str, str]
) -> None:
    assert client.post("/api/v1/users", json=payload).status_code == 201
    response = client.post(
        "/api/v1/users", json={**payload, "email": "user@example.com"}
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Email is already registered"}
    with Session(database) as session:
        assert len(session.scalars(select(User)).all()) == 1


@pytest.mark.parametrize(
    "field, value",
    [
        ("password", "short"),
        ("email", "invalid"),
        ("name", " "),
        ("business_id", str(uuid4())),
        ("is_active", False),
        ("password_hash", "injected-hash"),
        ("id", str(uuid4())),
    ],
)
def test_invalid_or_privileged_fields_are_rejected(
    client: TestClient,
    database: Engine,
    payload: dict[str, str],
    field: str,
    value: object,
) -> None:
    assert (
        client.post("/api/v1/users", json={**payload, field: value}).status_code == 422
    )
    with Session(database) as session:
        assert session.scalars(select(User)).all() == []


@pytest.mark.parametrize("field", ["name", "email", "password"])
def test_required_fields(
    client: TestClient, payload: dict[str, str], field: str
) -> None:
    payload.pop(field)
    assert client.post("/api/v1/users", json=payload).status_code == 422


@pytest.mark.parametrize(
    "error_type, status_code",
    [
        (UserConflictError, 409),
        (InvalidUserDataError, 422),
        (UserError, 500),
    ],
)
def test_registered_handler_supports_subclasses_and_hides_unknown_details(
    client: TestClient,
    payload: dict[str, str],
    error_type: type[UserError],
    status_code: int,
) -> None:
    subclass = type(
        "SpecificError", (type("IntermediateError", (error_type,), {}),), {}
    )
    service = Mock(spec=UserService)
    service.create.side_effect = subclass("Business error")
    app.dependency_overrides[get_user_service] = lambda: service
    try:
        response = client.post("/api/v1/users", json=payload)
        assert response.status_code == status_code
        assert response.json() == {
            "detail": "Internal server error"
            if status_code == 500
            else "Business error"
        }
    finally:
        app.dependency_overrides.pop(get_user_service)


def test_unexpected_errors_are_not_exposed(
    client: TestClient, payload: dict[str, str]
) -> None:
    service = Mock(spec=UserService)
    service.create.side_effect = RuntimeError("sensitive internal detail")
    app.dependency_overrides[get_user_service] = lambda: service
    try:
        with TestClient(app, raise_server_exceptions=False) as safe_client:
            response = safe_client.post("/api/v1/users", json=payload)
        assert response.status_code == 500
        assert "sensitive internal detail" not in response.text
    finally:
        app.dependency_overrides.pop(get_user_service)


def test_dependency_uses_same_session() -> None:
    session = Mock(spec=Session)
    service = get_user_service(session)
    assert service.session is session
    assert service.repository.session is session
