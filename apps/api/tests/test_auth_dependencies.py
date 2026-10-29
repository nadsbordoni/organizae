import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated
from unittest.mock import Mock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
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
    from app.core.config import settings
    from app.core.security import (
        create_access_token,
        decode_access_token,
        hash_password,
    )
    from app.db.session import get_db
    from app.modules.auth.dependencies import get_auth_service, get_current_user

from app.db.base import Base
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import AuthService
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.users.models import User
from app.modules.users.schemas import UserResponse

user_id, business_id, other_business_id = uuid4(), uuid4(), uuid4()


@pytest.fixture
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = secrets.token_urlsafe(64)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(secret))
    return secret


@pytest.fixture(scope="module")
def encoded_password() -> str:
    return hash_password("test-only-password")


@pytest.fixture
def database(encoded_password: str) -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        # These tables exist only in memory; application databases use Alembic.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine) as session:
            session.add(BusinessCategory(id=1, name="Beauty"))
            session.flush()
            session.add_all(
                [
                    Business(
                        id=identifier,
                        name=str(index),
                        category_id=1,
                        whatsapp="85999999999",
                        service_mode=ServiceMode.HIBRIDO,
                    )
                    for index, identifier in enumerate((business_id, other_business_id))
                ]
            )
            session.flush()
            session.add(
                User(
                    id=user_id,
                    name="User",
                    email="user@example.com",
                    password_hash=encoded_password,
                    is_active=True,
                    business_id=business_id,
                )
            )
            session.commit()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def app(database: Engine) -> FastAPI:
    app = FastAPI()

    def get_test_db() -> Iterator[Session]:
        with Session(database, autoflush=False) as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db

    @app.get("/private", response_model=UserResponse)
    def read_current_user(user: Annotated[User, Depends(get_current_user)]) -> User:
        return user

    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def test_real_login_and_authenticated_request(
    client: TestClient, database: Engine, jwt_secret: str
) -> None:
    with Session(database) as session:
        token = AuthService(session).login(
            LoginRequest(email="USER@EXAMPLE.COM", password="test-only-password")
        )
    assert token.token_type == "bearer"
    assert decode_access_token(token.access_token).sub == user_id
    response = client.get(
        "/private", headers={"Authorization": f"Bearer {token.access_token}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(user_id)
    assert response.json()["business_id"] == str(business_id)
    assert "password_hash" not in response.json()


@pytest.mark.parametrize("header", [None, "", "Basic credentials", "Bearer", "Bearer "])
def test_missing_or_wrong_authentication_returns_bearer_challenge(
    client: TestClient, header: str | None
) -> None:
    response = client.get(
        "/private", headers={} if header is None else {"Authorization": header}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize(
    "invalidity",
    [
        "expired",
        "signature",
        "subject",
        "unknown_user",
        "purpose",
        "missing_exp",
        "unsigned",
    ],
)
def test_invalid_tokens_and_unknown_users_are_rejected(
    client: TestClient, jwt_secret: str, invalidity: str
) -> None:
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": str(user_id),
        "iat": now - 60,
        "exp": now + 60,
        "token_type": "access",
    }
    if invalidity == "expired":
        payload["exp"] = now - 1
    elif invalidity == "subject":
        payload["sub"] = "invalid"
    elif invalidity == "unknown_user":
        payload["sub"] = str(uuid4())
    elif invalidity == "purpose":
        payload["token_type"] = "refresh"
    elif invalidity == "missing_exp":
        payload.pop("exp")
    key = secrets.token_urlsafe(64) if invalidity == "signature" else jwt_secret
    token = jwt.encode(
        payload,
        key if invalidity != "unsigned" else "",
        algorithm="HS256" if invalidity != "unsigned" else "none",
    )
    response = client.get("/private", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize("action", ["deactivate", "remove"])
def test_valid_token_stops_authenticating_after_account_changes(
    client: TestClient, database: Engine, jwt_secret: str, action: str
) -> None:
    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/private", headers=headers).status_code == 200
    with Session(database) as session:
        user = session.get(User, user_id)
        if action == "deactivate":
            user.is_active = False
        else:
            session.delete(user)
        session.commit()
    response = client.get("/private", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_business_is_read_from_current_database_state(
    client: TestClient, database: Engine, jwt_secret: str
) -> None:
    token = create_access_token(user_id)
    with Session(database) as session:
        session.get(User, user_id).business_id = other_business_id
        session.commit()
    response = client.get(
        "/private",
        params={"business_id": str(business_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["business_id"] == str(other_business_id)


def test_missing_signing_key_is_a_server_error_not_bad_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(""))
    response = client.get("/private", headers={"Authorization": "Bearer token"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Authentication is unavailable"}
    assert "JWT_SECRET_KEY" not in response.text
    assert "WWW-Authenticate" not in response.headers


def test_database_errors_are_not_replaced_with_http_401() -> None:
    service = Mock(spec=AuthService)
    error = OperationalError("statement", {}, Exception("database unavailable"))
    service.get_current_user.side_effect = error
    with pytest.raises(OperationalError) as caught:
        get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"), service
        )
    assert caught.value is error


def test_openapi_documents_http_bearer(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    security = schema["components"]["securitySchemes"]["HTTPBearer"]
    assert security["scheme"] == "bearer"
    assert security["bearerFormat"] == "JWT"
    assert schema["paths"]["/private"]["get"]["security"] == [{"HTTPBearer": []}]


def test_auth_service_dependency_uses_same_session() -> None:
    session = Mock(spec=Session)
    service = get_auth_service(session)
    assert service.session is session
    assert service.repository.session is session
