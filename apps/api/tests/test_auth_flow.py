import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from sqlite3 import Connection
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, event, func, insert, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

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
    from app.main import app

from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.models import Professional
from app.modules.services.associations import professional_services
from app.modules.services.models import Service
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

user_a, user_b, new_user, inactive_user = uuid4(), uuid4(), uuid4(), uuid4()
business_a, business_b = uuid4(), uuid4()
service_a, service_b, professional_a, professional_b = (
    uuid4(),
    uuid4(),
    uuid4(),
    uuid4(),
)
business_data = {
    "name": "New business",
    "category_id": 1,
    "whatsapp": "85999999999",
    "service_mode": "HIBRIDO",
}
service_data = {"name": "New service", "price": "25.50", "duration_minutes": 30}
professional_data = {"name": "New professional", "service_ids": [str(service_a)]}


def headers_for(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


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

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        connection: Connection, record: ConnectionPoolEntry
    ) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        # Production databases are migrated separately; this database is disposable.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine) as session:
            session.add(BusinessCategory(id=1, name="Beauty"))
            session.flush()
            session.add_all(
                [
                    Business(
                        id=identifier,
                        name=name,
                        category_id=1,
                        whatsapp="85999999999",
                        service_mode=ServiceMode.HIBRIDO,
                    )
                    for identifier, name in ((business_a, "A"), (business_b, "B"))
                ]
            )
            session.flush()
            session.add_all(
                [
                    User(
                        id=identifier,
                        name=name,
                        email=f"{name}@example.com",
                        password_hash=password_hash,
                        business_id=owner,
                        is_active=active,
                    )
                    for identifier, name, owner, active in (
                        (user_a, "a", business_a, True),
                        (user_b, "b", business_b, True),
                        (new_user, "new", None, True),
                        (inactive_user, "inactive", None, False),
                    )
                ]
            )
            session.add_all(
                [
                    Service(
                        id=identifier,
                        business_id=owner,
                        name=name,
                        price=25,
                        duration_minutes=30,
                    )
                    for identifier, owner, name in (
                        (service_a, business_a, "A"),
                        (service_b, business_b, "B"),
                    )
                ]
            )
            session.add_all(
                [
                    Professional(id=identifier, business_id=owner, name=name)
                    for identifier, owner, name in (
                        (professional_a, business_a, "A"),
                        (professional_b, business_b, "B"),
                    )
                ]
            )
            session.flush()
            session.execute(
                insert(professional_services),
                [
                    {
                        "professional_id": professional_a,
                        "service_id": service_a,
                        "business_id": business_a,
                    },
                    {
                        "professional_id": professional_b,
                        "service_id": service_b,
                        "business_id": business_b,
                    },
                ],
            )
            session.commit()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def client(database: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        settings, "JWT_SECRET_KEY", SecretStr(secrets.token_urlsafe(64))
    )

    def get_test_db() -> Iterator[Session]:
        with Session(database, autoflush=False, expire_on_commit=True) as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db)


def test_login_returns_access_token_and_prevents_caching(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "A@EXAMPLE.COM", "password": "test-only-password"},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type"}
    assert response.json()["token_type"] == "bearer"
    assert decode_access_token(response.json()["access_token"]).sub == user_a
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"


@pytest.mark.parametrize(
    "email, password",
    [
        ("unknown@example.com", "test-only-password"),
        ("a@example.com", "wrong-password"),
        ("inactive@example.com", "test-only-password"),
    ],
)
def test_failed_logins_have_same_response(
    client: TestClient, email: str, password: str
) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid email or password"}


protected_requests = [
    ("GET", "/businesses", None),
    ("POST", "/businesses", business_data),
    ("GET", f"/businesses/{business_a}", None),
    ("PATCH", f"/businesses/{business_a}", {"name": "Changed"}),
    ("DELETE", f"/businesses/{business_a}", None),
    ("GET", "/services", None),
    ("POST", "/services", service_data),
    ("GET", f"/services/{service_a}", None),
    ("PATCH", f"/services/{service_a}", {"name": "Changed"}),
    ("DELETE", f"/services/{service_a}", None),
    ("GET", "/professionals", None),
    ("POST", "/professionals", professional_data),
    ("GET", f"/professionals/{professional_a}", None),
    ("PATCH", f"/professionals/{professional_a}", {"name": "Changed"}),
    ("PUT", f"/professionals/{professional_a}/services", {"service_ids": []}),
    ("DELETE", f"/professionals/{professional_a}", None),
]


@pytest.mark.parametrize("method, path, payload", protected_requests)
@pytest.mark.parametrize(
    "authentication", ["missing", "invalid", "expired", "inactive"]
)
def test_all_resource_endpoints_require_active_authenticated_user(
    client: TestClient,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    authentication: str,
) -> None:
    headers = {}
    if authentication == "invalid":
        headers = {"Authorization": "Bearer invalid"}
    elif authentication == "inactive":
        headers = headers_for(inactive_user)
    elif authentication == "expired":
        now = int(datetime.now(UTC).timestamp())
        token = jwt.encode(
            {
                "sub": str(user_a),
                "iat": now - 60,
                "exp": now - 1,
                "token_type": "access",
            },
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {token}"}
    response = client.request(method, f"/api/v1{path}", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "access_token" not in response.json()


@pytest.mark.parametrize(
    "method, path, payload",
    [
        ("GET", f"/businesses/{business_b}", None),
        ("PATCH", f"/businesses/{business_b}", {"name": "Changed"}),
        ("DELETE", f"/businesses/{business_b}", None),
        ("GET", f"/services/{service_b}", None),
        ("PATCH", f"/services/{service_b}", {"name": "Changed"}),
        ("DELETE", f"/services/{service_b}", None),
        ("GET", f"/professionals/{professional_b}", None),
        ("PATCH", f"/professionals/{professional_b}", {"name": "Changed"}),
        ("DELETE", f"/professionals/{professional_b}", None),
        ("PUT", f"/professionals/{professional_b}/services", {"service_ids": []}),
    ],
)
def test_foreign_resource_ids_cannot_be_read_or_mutated(
    client: TestClient, method: str, path: str, payload: dict[str, object] | None
) -> None:
    response = client.request(
        method,
        f"/api/v1{path}",
        json=payload,
        params={"business_id": str(business_b)},
        headers=headers_for(user_a),
    )
    assert response.status_code == 404
    # Its real owner can still read the untouched resource.
    own_path = (
        path.removesuffix("/services") if path.startswith("/professionals/") else path
    )
    original = client.get(f"/api/v1{own_path}", headers=headers_for(user_b))
    assert original.status_code == 200
    assert original.json()["name"] == "B"


@pytest.mark.parametrize("resource", ["businesses", "services", "professionals"])
def test_lists_use_authenticated_business_and_ignore_client_tenant_query(
    client: TestClient, resource: str
) -> None:
    response = client.get(
        f"/api/v1/{resource}",
        headers=headers_for(user_a),
        params={"business_id": str(business_b)},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "A"
    if resource != "businesses":
        assert response.json()[0]["business_id"] == str(business_a)


@pytest.mark.parametrize(
    "resource, payload",
    [("services", service_data), ("professionals", professional_data)],
)
def test_creation_assigns_business_from_identity_and_rejects_client_business(
    client: TestClient, resource: str, payload: dict[str, object]
) -> None:
    response = client.post(
        f"/api/v1/{resource}",
        json=payload,
        headers=headers_for(user_a),
        params={"business_id": str(business_b)},
    )
    assert response.status_code == 201
    assert response.json()["business_id"] == str(business_a)
    response = client.post(
        f"/api/v1/{resource}",
        json={**payload, "business_id": str(business_b)},
        headers=headers_for(user_a),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "ids", [[str(service_b)], [str(uuid4())], [str(service_a), str(service_a)]]
)
def test_service_associations_remain_scoped_and_atomic(
    client: TestClient, ids: list[str]
) -> None:
    response = client.put(
        f"/api/v1/professionals/{professional_a}/services",
        json={"service_ids": ids},
        headers=headers_for(user_a),
    )
    assert response.status_code == 422
    original = client.get(
        f"/api/v1/professionals/{professional_a}", headers=headers_for(user_a)
    ).json()
    assert [item["id"] for item in original["services"]] == [str(service_a)]


def test_public_signup_login_and_first_business_share_one_ownership_transaction(
    client: TestClient, database: Engine
) -> None:
    response = client.post(
        "/api/v1/users",
        json={
            "name": "New owner",
            "email": "owner@example.com",
            "password": "test-only-password",
        },
    )
    assert response.status_code == 201
    assert "password_hash" not in response.json()
    assert response.json()["business_id"] is None
    identifier = UUID(response.json()["id"])
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "test-only-password"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/services", headers=headers).status_code == 403
    response = client.post("/api/v1/businesses", json=business_data, headers=headers)
    assert response.status_code == 201
    business_identifier = UUID(response.json()["id"])
    with Session(database) as session:
        assert session.get(User, identifier).business_id == business_identifier
        assert session.get(Business, business_identifier) is not None
    # The same JWT now sees the linked business without being reissued.
    assert client.get("/api/v1/businesses", headers=headers).json()[0]["id"] == str(
        business_identifier
    )
    assert client.get("/api/v1/services", headers=headers).json() == []
    assert (
        client.post(
            "/api/v1/businesses", json=business_data, headers=headers
        ).status_code
        == 409
    )
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Business)) == 3


@pytest.mark.parametrize(
    "resource, payload",
    [("services", service_data), ("professionals", professional_data)],
)
def test_user_without_business_cannot_access_tenant_resources(
    client: TestClient, resource: str, payload: dict[str, object]
) -> None:
    headers = headers_for(new_user)
    assert client.get(f"/api/v1/{resource}", headers=headers).status_code == 403
    assert (
        client.post(f"/api/v1/{resource}", headers=headers, json=payload).status_code
        == 403
    )


@pytest.mark.parametrize("failure_stage", ["link", "commit"])
def test_failed_onboarding_rolls_back_both_business_and_user_link(
    client: TestClient,
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    headers = headers_for(new_user)
    with monkeypatch.context() as changes:
        if failure_stage == "link":
            original = UserRepository.update

            def fail_after_link(
                repository: UserRepository, user: User, **fields: object
            ) -> User:
                original(repository, user, **fields)
                raise RuntimeError("forced failure after flush")

            changes.setattr(UserRepository, "update", fail_after_link)
        else:

            def fail_commit(session: Session) -> None:
                raise RuntimeError("forced commit failure")

            changes.setattr(Session, "commit", fail_commit)
        response = client.post(
            "/api/v1/businesses", json=business_data, headers=headers
        )
        assert response.status_code == 500
        assert "forced" not in response.text
    with Session(database) as session:
        assert session.get(User, new_user).business_id is None
        assert session.scalar(select(func.count()).select_from(Business)) == 2
    assert (
        client.post(
            "/api/v1/businesses", json=business_data, headers=headers
        ).status_code
        == 201
    )


def test_invalid_category_leaves_no_orphan_business(
    client: TestClient, database: Engine
) -> None:
    response = client.post(
        "/api/v1/businesses",
        json={**business_data, "category_id": 999},
        headers=headers_for(new_user),
    )
    assert response.status_code == 422
    with Session(database) as session:
        assert session.get(User, new_user).business_id is None
        assert session.scalar(select(func.count()).select_from(Business)) == 2


def test_login_configuration_error_does_not_expose_secret_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(""))
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "test-only-password"},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Authentication is unavailable"}


@pytest.mark.parametrize(
    "path, payload, sensitive_value",
    [
        ("/auth/login", {"email": "a@example.com", "password": "x" * 129}, "x" * 129),
        (
            "/users",
            {"name": "User", "email": "user@example.com", "password": "s3cr3t"},
            "s3cr3t",
        ),
        (
            "/auth/login",
            {"email": "a@example.com", "password": {"value": "sensitive-password"}},
            "sensitive-password",
        ),
        (
            "/users",
            {
                "name": "User",
                "email": "user@example.com",
                "password": "test-only-password",
                "password_hash": "sensitive-hash",
            },
            "sensitive-hash",
        ),
    ],
)
def test_validation_errors_do_not_echo_credentials(
    client: TestClient, path: str, payload: dict[str, object], sensitive_value: str
) -> None:
    response = client.post(f"/api/v1{path}", json=payload)
    assert response.status_code == 422
    assert sensitive_value not in response.text
    assert response.json()["detail"]
    for error in response.json()["detail"]:
        assert {"type", "loc", "msg"} <= set(error)
        assert "input" not in error
        assert "ctx" not in error


def test_deleting_owned_empty_business_preserves_user(
    client: TestClient, database: Engine
) -> None:
    headers = headers_for(new_user)
    created = client.post("/api/v1/businesses", json=business_data, headers=headers)
    assert created.status_code == 201
    identifier = UUID(created.json()["id"])
    assert (
        client.delete(f"/api/v1/businesses/{identifier}", headers=headers).status_code
        == 204
    )
    with Session(database) as session:
        user = session.get(User, new_user)
        assert user.is_active is True
        assert user.business_id is None
        assert session.get(Business, identifier) is None


def test_protected_openapi_contract_has_no_client_business_id(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    for resource in ("businesses", "services", "professionals"):
        path = schema["paths"][f"/api/v1/{resource}"]
        assert path["get"]["security"]
        assert path["post"]["security"]
        assert all(
            parameter["name"] != "business_id"
            for parameter in path["get"].get("parameters", [])
        )
    assert (
        "business_id"
        not in schema["components"]["schemas"]["ServiceCreateRequest"]["properties"]
    )
    assert (
        "business_id"
        not in schema["components"]["schemas"]["ProfessionalCreateRequest"][
            "properties"
        ]
    )
    assert not schema["paths"]["/api/v1/auth/login"]["post"].get("security")
    assert not schema["paths"]["/api/v1/users"]["post"].get("security")
