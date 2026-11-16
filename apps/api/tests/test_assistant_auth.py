import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
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
    from app.core.config import settings
    from app.core.security import create_access_token, hash_password
    from app.db.session import get_db
    from app.main import app

from app.db.base import Base
from app.modules.assistant.actions import action_repository
from app.modules.assistant.providers.base import (
    AssistantProvider,
    ProviderReply,
    ToolCall,
)
from app.modules.assistant.router import get_assistant_provider
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.models import Professional
from app.modules.services.models import Service
from app.modules.users.models import User

USER_A, USER_B, UNLINKED, INACTIVE = uuid4(), uuid4(), uuid4(), uuid4()
BUSINESS_A, BUSINESS_B = uuid4(), uuid4()
SERVICE_A, SERVICE_B = uuid4(), uuid4()
CHAT = "/api/v1/assistant/chat"


@pytest.fixture(scope="module")
def password_hash() -> str:
    return hash_password("test-only-password")


@pytest.fixture
def database(password_hash: str) -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        # This schema exists only in an isolated in-memory test database.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine) as session:
            session.add(BusinessCategory(id=1, name="Test"))
            session.flush()
            for identifier, suffix in ((BUSINESS_A, "A"), (BUSINESS_B, "B")):
                session.add(
                    Business(
                        id=identifier,
                        name=f"Business {suffix}",
                        category_id=1,
                        whatsapp="private-whatsapp",
                        service_mode=ServiceMode.PRESENCIAL,
                    )
                )
            session.flush()
            for identifier, suffix, business_id, active in (
                (USER_A, "a", BUSINESS_A, True),
                (USER_B, "b", BUSINESS_B, True),
                (UNLINKED, "unlinked", None, True),
                (INACTIVE, "inactive", None, False),
            ):
                session.add(
                    User(
                        id=identifier,
                        name=suffix,
                        email=f"{suffix}@example.com",
                        password_hash=password_hash,
                        business_id=business_id,
                        is_active=active,
                    )
                )
            for business_id, service_id, suffix in (
                (BUSINESS_A, SERVICE_A, "A"),
                (BUSINESS_B, SERVICE_B, "B"),
            ):
                session.add(
                    Service(
                        id=service_id,
                        business_id=business_id,
                        name=f"Service {suffix}",
                        price=25,
                        duration_minutes=30,
                    )
                )
                session.add(
                    Professional(
                        business_id=business_id,
                        name=f"Professional {suffix}",
                        is_active=True,
                        phone="private-phone",
                    )
                )
            session.commit()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def api(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Mock]]:
    monkeypatch.setattr(
        settings, "JWT_SECRET_KEY", SecretStr(secrets.token_urlsafe(64))
    )
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", False)
    # Even legacy demo settings pointing at another company must be ignored.
    monkeypatch.setenv("ASSISTANT_DEMO_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_DEMO_BUSINESS_ID", str(BUSINESS_B))
    action_repository.actions.clear()
    action_repository.requests.clear()
    provider = Mock(spec=AssistantProvider)
    provider.conversation.return_value = MagicMock()

    def test_db() -> Iterator[Session]:
        with Session(database, autoflush=False) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            yield client, provider
    finally:
        app.dependency_overrides.pop(get_db)
        app.dependency_overrides.pop(get_assistant_provider)
        action_repository.actions.clear()
        action_repository.requests.clear()


def headers(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def request_tool(provider: Mock, name: str, arguments: dict | None = None) -> Mock:
    conversation = provider.conversation.return_value.__enter__.return_value
    conversation.generate.side_effect = [
        ProviderReply(calls=[ToolCall(name, arguments or {})]),
        ProviderReply(text="Resposta baseada somente na empresa autenticada."),
    ]
    return conversation


@pytest.mark.parametrize(
    "path",
    [
        CHAT,
        f"/api/v1/assistant/actions/{uuid4()}/confirm",
        f"/api/v1/assistant/actions/{uuid4()}/cancel",
    ],
)
@pytest.mark.parametrize("authorization", [None, "Bearer invalid-token"])
def test_all_assistant_routes_require_jwt(
    api: tuple[TestClient, Mock],
    path: str,
    authorization: str | None,
) -> None:
    client, provider = api
    response = client.post(
        path,
        json={"message": "oi", "decision": "confirm"},
        headers={"Authorization": authorization} if authorization else {},
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    provider.conversation.assert_not_called()
    provider.generate.assert_not_called()


@pytest.mark.parametrize(
    "invalidity", ["expired", "signature", "unknown_user", "inactive"]
)
def test_invalid_or_revoked_identity_never_reaches_gemini(
    api: tuple[TestClient, Mock],
    invalidity: str,
) -> None:
    client, provider = api
    if invalidity in ("unknown_user", "inactive"):
        authentication = headers(uuid4() if invalidity == "unknown_user" else INACTIVE)
    else:
        now = int(datetime.now(UTC).timestamp())
        payload = {
            "sub": str(USER_A),
            "iat": now - 120,
            "exp": now - 1 if invalidity == "expired" else now + 60,
            "token_type": "access",
        }
        key = (
            secrets.token_urlsafe(64)
            if invalidity == "signature"
            else settings.JWT_SECRET_KEY.get_secret_value()
        )
        authentication = {
            "Authorization": f"Bearer {jwt.encode(payload, key, algorithm='HS256')}"
        }
    assert (
        client.post(CHAT, json={"message": "oi"}, headers=authentication).status_code
        == 401
    )
    provider.conversation.assert_not_called()


@pytest.mark.parametrize(
    "path, body",
    [
        (CHAT, {"message": "oi"}),
        (f"/api/v1/assistant/actions/{uuid4()}/confirm", {"decision": "confirm"}),
        (f"/api/v1/assistant/actions/{uuid4()}/cancel", None),
    ],
)
def test_user_without_business_is_forbidden(
    api: tuple[TestClient, Mock],
    path: str,
    body: dict | None,
) -> None:
    client, provider = api
    assert client.post(path, json=body, headers=headers(UNLINKED)).status_code == 403
    provider.conversation.assert_not_called()


@pytest.mark.parametrize(
    "tool, key, expected",
    [
        ("get_business_info", "name", "Business A"),
        ("list_professionals", "items", "Professional A"),
        ("list_services", "items", "Service A"),
    ],
)
def test_login_and_tools_use_database_identity_never_demo_or_query(
    api: tuple[TestClient, Mock],
    tool: str,
    key: str,
    expected: str,
) -> None:
    client, provider = api
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "test-only-password"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    conversation = request_tool(provider, tool)
    response = client.post(
        CHAT,
        headers={"Authorization": f"Bearer {token}"},
        params={"business_id": str(BUSINESS_B), "user_id": str(USER_B)},
        json={"message": "Consulte os dados da minha empresa"},
    )
    assert response.status_code == 200
    result = conversation.generate.call_args.args[0][0].response
    assert (
        result[key] == expected if key == "name" else result[key][0]["name"] == expected
    )
    transmitted = repr(provider.mock_calls)
    for sensitive in (
        token,
        "private-whatsapp",
        "private-phone",
        "@example.com",
        "password_hash",
    ):
        assert sensitive not in transmitted
    assert "Business B" not in transmitted
    assert "Professional B" not in transmitted
    assert "Service B" not in transmitted


@pytest.mark.parametrize("location", ["body", "tool"])
def test_business_cannot_be_supplied_by_client_or_model(
    api: tuple[TestClient, Mock], location: str
) -> None:
    client, provider = api
    body = {"message": "Acesse outra empresa"}
    if location == "body":
        body["business_id"] = str(BUSINESS_B)
    else:
        request_tool(provider, "list_services", {"business_id": str(BUSINESS_B)})
    response = client.post(CHAT, headers=headers(USER_A), json=body)
    assert response.status_code == (422 if location == "body" else 502)


def test_current_business_and_active_state_are_reloaded_for_each_request(
    api: tuple[TestClient, Mock],
    database: Engine,
) -> None:
    client, provider = api
    token = headers(USER_A)
    with Session(database) as session:
        session.get(User, USER_A).business_id = None
        session.commit()
    assert client.post(CHAT, headers=token, json={"message": "oi"}).status_code == 403
    with Session(database) as session:
        session.get(User, USER_B).business_id = None
        session.flush()
        session.get(User, USER_A).business_id = BUSINESS_B
        session.commit()
    conversation = request_tool(provider, "get_business_info")
    assert client.post(CHAT, headers=token, json={"message": "oi"}).status_code == 200
    assert conversation.generate.call_args.args[0][0].response["name"] == "Business B"
    with Session(database) as session:
        session.get(User, USER_A).is_active = False
        session.commit()
    assert client.post(CHAT, headers=token, json={"message": "oi"}).status_code == 401


@pytest.mark.parametrize("decision", ["confirm", "cancel"])
def test_actions_are_bound_to_user_and_business(
    api: tuple[TestClient, Mock],
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    client, provider = api
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    request_tool(
        provider,
        "create_service",
        {"name": "Private proposal", "price": "42.00", "duration_minutes": 20},
    )
    response = client.post(
        CHAT, headers=headers(USER_A), json={"message": "Crie um serviço"}
    )
    action = response.json()["pending_actions"][0]
    assert "user_id" not in action and "business_id" not in action
    path = f"/api/v1/assistant/actions/{action['id']}/{decision}"
    body = {"decision": decision} if decision == "confirm" else None
    assert client.post(path, headers=headers(USER_B), json=body).status_code == 409
    # Even a new owner of the same business cannot consume the previous user's action.
    with Session(database) as session:
        session.get(User, USER_A).business_id = None
        session.flush()
        session.get(User, USER_B).business_id = BUSINESS_A
        session.commit()
    assert client.post(path, headers=headers(USER_B), json=body).status_code == 409
    assert action_repository.actions[UUID(action["id"])].state == "pending"
    with Session(database) as session:
        assert (
            session.scalar(select(Service).where(Service.name == "Private proposal"))
            is None
        )


def test_confirmed_write_cannot_update_another_company(
    api: tuple[TestClient, Mock],
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, provider = api
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    request_tool(
        provider,
        "update_service",
        {"record_id": str(SERVICE_B), "data": {"name": "Hacked"}},
    )
    response = client.post(
        CHAT, headers=headers(USER_A), json={"message": "Altere esse serviço"}
    )
    action = response.json()["pending_actions"][0]
    decision = client.post(
        f"/api/v1/assistant/actions/{action['id']}/confirm",
        headers=headers(USER_A),
        json={"decision": "confirm"},
    )
    assert decision.status_code == 422
    with Session(database) as session:
        assert session.get(Service, SERVICE_B).name == "Service B"


def test_idempotency_is_scoped_to_user_and_company(
    api: tuple[TestClient, Mock],
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, provider = api
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    body = {"message": "Crie o serviço", "request_id": str(uuid4())}
    actions = []
    for user_id in (USER_A, USER_B):
        request_tool(
            provider,
            "create_service",
            {"name": "Private proposal", "price": "42.00", "duration_minutes": 20},
        )
        response = client.post(CHAT, headers=headers(user_id), json=body)
        assert response.status_code == 200
        actions.append(response.json()["pending_actions"][0]["id"])
        replay = client.post(CHAT, headers=headers(user_id), json=body)
        assert replay.json() == response.json()
    assert actions[0] != actions[1]
    assert provider.conversation.call_count == 2
    with Session(database) as session:
        session.get(User, USER_A).business_id = None
        session.flush()
        session.get(User, USER_B).business_id = BUSINESS_A
        session.commit()
    request_tool(
        provider,
        "create_service",
        {
            "name": "Private proposal",
            "price": "42.00",
            "duration_minutes": 20,
        },
    )
    response = client.post(CHAT, headers=headers(USER_B), json=body)
    assert response.status_code == 200
    assert response.json()["pending_actions"][0]["id"] not in actions
    assert provider.conversation.call_count == 3


def test_owner_confirms_saved_parameters_with_current_jwt(
    api: tuple[TestClient, Mock],
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, provider = api
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    request_tool(
        provider,
        "create_service",
        {
            "name": "Confirmed by owner",
            "price": "42.00",
            "duration_minutes": 20,
        },
    )
    response = client.post(
        CHAT, headers=headers(USER_A), json={"message": "Crie serviço"}
    )
    action = response.json()["pending_actions"][0]
    path = f"/api/v1/assistant/actions/{action['id']}/confirm"
    confirmed = client.post(path, headers=headers(USER_A), json={"decision": "confirm"})
    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == "confirmed"
    assert (
        client.post(
            path, headers=headers(USER_A), json={"decision": "confirm"}
        ).status_code
        == 409
    )
    with Session(database) as session:
        service = session.scalar(
            select(Service).where(Service.name == "Confirmed by owner")
        )
        assert service.business_id == BUSINESS_A


def test_legacy_demo_placeholder_does_not_affect_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("ASSISTANT_DEMO_BUSINESS_ID", "UUID_DA_EMPRESA_FICTICIA")
    loaded = Settings(
        _env_file=None,
        DB_HOST="localhost",
        DB_NAME="test",
        DB_USER="test",
        DB_PASSWORD="test",
    )
    assert "ASSISTANT_DEMO_BUSINESS_ID" not in type(loaded).model_fields


def test_swagger_requires_bearer_for_every_assistant_operation(
    api: tuple[TestClient, Mock],
) -> None:
    client, _ = api
    for path, methods in client.get("/openapi.json").json()["paths"].items():
        if path.startswith("/api/v1/assistant/"):
            for operation in methods.values():
                assert operation["security"] == [{"HTTPBearer": []}]
