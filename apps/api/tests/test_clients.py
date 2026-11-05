import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
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
    from app.core.security import create_access_token, hash_password
    from app.db.session import get_db
    from app.main import app

from app.db.base import Base
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
)
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.clients.exceptions import (
    ClientConflictError,
    ClientError,
    ClientNotFoundError,
)
from app.modules.clients.models import Client
from app.modules.clients.repository import ClientRepository
from app.modules.clients.schemas import ClientCreate, ClientUpdate
from app.modules.clients.service import ClientService
from app.modules.professionals.models import Professional
from app.modules.services.models import Service
from app.modules.users.models import User

business_a, business_b = uuid4(), uuid4()
owner_a, owner_b, inactive_user, unassigned_user = uuid4(), uuid4(), uuid4(), uuid4()
client_a, client_b, other_client = uuid4(), uuid4(), uuid4()
service_a, service_b, professional_a, professional_b = (
    uuid4(),
    uuid4(),
    uuid4(),
    uuid4(),
)
base_url = "/api/v1/clients"
new_client = {
    "name": "  New client  ",
    "phone": "(85) 98888-7777",
    "email": "client@example.com",
    "notes": "  Prefers mornings  ",
}


def auth_headers(user_id: UUID = owner_a) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


@pytest.fixture(scope="module")
def password_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


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
        # Only this disposable test database is created from ORM metadata.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine) as session:
            session.add(BusinessCategory(id=1, name="Beauty"))
            session.flush()
            session.add_all(
                Business(
                    id=identifier,
                    name=name,
                    category_id=1,
                    whatsapp="85999999999",
                    service_mode=ServiceMode.PRESENCIAL,
                )
                for identifier, name in ((business_a, "A"), (business_b, "B"))
            )
            session.flush()
            session.add_all(
                User(
                    id=identifier,
                    name=name,
                    email=f"{name}@example.com",
                    password_hash=password_hash,
                    is_active=active,
                    business_id=business_id,
                )
                for identifier, name, active, business_id in (
                    (owner_a, "owner_a", True, business_a),
                    (owner_b, "owner_b", True, business_b),
                    (inactive_user, "inactive", False, None),
                    (unassigned_user, "unassigned", True, None),
                )
            )
            session.add_all(
                Client(
                    id=identifier,
                    business_id=business_id,
                    name=name,
                    phone=phone,
                    email=email,
                    notes="Original notes",
                )
                for identifier, business_id, name, phone, email in (
                    (client_a, business_a, "Alice", "85999999999", "alice@example.com"),
                    (client_b, business_a, "Bob", "85977777777", None),
                    (other_client, business_b, "Foreign", "85999999999", None),
                )
            )
            session.add_all(
                Service(
                    id=identifier,
                    business_id=business_id,
                    name="Haircut",
                    price=25,
                    duration_minutes=30,
                )
                for identifier, business_id in (
                    (service_a, business_a),
                    (service_b, business_b),
                )
            )
            session.add_all(
                Professional(
                    id=identifier, business_id=business_id, name="Professional"
                )
                for identifier, business_id in (
                    (professional_a, business_a),
                    (professional_b, business_b),
                )
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


def test_create_normalizes_and_serializes_after_commit(
    client: TestClient, database: Engine
) -> None:
    response = client.post(base_url, json=new_client, headers=auth_headers())
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"]).version == 4
    assert body == {
        "id": body["id"],
        "business_id": str(business_a),
        "name": "New client",
        "phone": "85988887777",
        "email": "client@example.com",
        "notes": "Prefers mornings",
        "created_at": body["created_at"],
    }
    assert datetime.fromisoformat(body["created_at"])
    with Session(database) as session:
        stored = session.get(Client, UUID(body["id"]))
        assert stored.phone == body["phone"]
        assert stored.business_id == business_a


def test_create_with_only_required_fields(client: TestClient) -> None:
    response = client.post(
        base_url,
        json={"name": "Client", "phone": "(85) 98888-7777"},
        headers=auth_headers(),
    )
    assert response.status_code == 201
    assert response.json()["email"] is None
    assert response.json()["notes"] is None


@pytest.mark.parametrize("phone", ["85999999999", "(85) 99999-9999", "85 99999 9999"])
def test_duplicate_normalized_phone_in_same_business_returns_conflict(
    client: TestClient, database: Engine, phone: str
) -> None:
    response = client.post(
        base_url, json={**new_client, "phone": phone}, headers=auth_headers()
    )
    assert response.status_code == 409
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Client)) == 3


def test_same_phone_is_allowed_in_another_business(client: TestClient) -> None:
    for user_id in (owner_a, owner_b):
        response = client.post(base_url, json=new_client, headers=auth_headers(user_id))
        assert response.status_code == 201


def test_database_rejects_duplicate_when_precheck_misses_a_concurrent_insert(
    client: TestClient, database: Engine
) -> None:
    with (
        patch.object(ClientRepository, "get_by_phone", return_value=None),
        patch.object(Session, "commit") as commit,
    ):
        response = client.post(
            base_url,
            json={**new_client, "phone": "(85) 99999-9999"},
            headers=auth_headers(),
        )
        assert response.status_code == 409
        assert "INSERT" not in response.text
        commit.assert_not_called()
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Client)) == 3


def test_get_and_partial_update_keep_omitted_fields(client: TestClient) -> None:
    response = client.get(f"{base_url}/{client_a}", headers=auth_headers())
    assert response.status_code == 200
    original = response.json()
    response = client.patch(
        f"{base_url}/{client_a}", json={"name": "  Alicia  "}, headers=auth_headers()
    )
    assert response.status_code == 200
    assert response.json() == {**original, "name": "Alicia"}
    response = client.patch(
        f"{base_url}/{client_a}",
        json={"email": None, "notes": None, "phone": "(85) 99999-9999"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["phone"] == original["phone"]
    assert response.json()["email"] is None
    assert response.json()["notes"] is None


def test_update_phone_normalizes_and_conflicts_do_not_change_other_fields(
    client: TestClient,
) -> None:
    response = client.patch(
        f"{base_url}/{client_a}",
        json={"phone": new_client["phone"]},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["phone"] == "85988887777"
    response = client.patch(
        f"{base_url}/{client_a}",
        json={"name": "Changed", "phone": "(85) 97777-7777"},
        headers=auth_headers(),
    )
    assert response.status_code == 409
    response = client.get(f"{base_url}/{client_a}", headers=auth_headers())
    assert response.json()["name"] == "Alice"
    assert response.json()["phone"] == "85988887777"


def test_list_is_scoped_and_paginated_and_ignores_client_tenant(
    client: TestClient,
) -> None:
    response = client.get(
        base_url, params={"business_id": str(business_b)}, headers=auth_headers()
    )
    assert [item["id"] for item in response.json()] == [str(client_a), str(client_b)]
    response = client.get(
        base_url, params={"offset": 1, "limit": 1}, headers=auth_headers()
    )
    assert [item["id"] for item in response.json()] == [str(client_b)]
    response = client.get(base_url, params={"offset": 2}, headers=auth_headers())
    assert response.json() == []


@pytest.mark.parametrize(
    ("search", "expected"),
    [("ali", client_a), ("ALICE@EXAMPLE", client_a), ("(85) 97777-7777", client_b)],
)
def test_search_matches_name_email_and_normalized_phone(
    client: TestClient, search: str, expected: UUID
) -> None:
    response = client.get(base_url, params={"search": search}, headers=auth_headers())
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(expected)]


@pytest.mark.parametrize("search", ["Foreign", "' OR 1=1 --", "%", "_"])
def test_search_does_not_leak_other_tenants_or_interpret_sql_wildcards(
    client: TestClient, search: str
) -> None:
    response = client.get(base_url, params={"search": search}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == []


protected_routes = [
    ("POST", "", new_client),
    ("GET", "", None),
    ("GET", f"/{client_a}", None),
    ("PATCH", f"/{client_a}", {"name": "Changed"}),
    ("GET", f"/{client_a}/appointments", None),
]


@pytest.mark.parametrize(("method", "path", "payload"), protected_routes)
@pytest.mark.parametrize("identity", ["missing", "invalid", "inactive", "unassigned"])
def test_all_routes_require_active_authenticated_user_with_business(
    client: TestClient, method: str, path: str, payload: dict | None, identity: str
) -> None:
    headers = {
        "missing": {},
        "invalid": {"Authorization": "Bearer invalid-token"},
        "inactive": auth_headers(inactive_user),
        "unassigned": auth_headers(unassigned_user),
    }[identity]
    response = client.request(method, base_url + path, json=payload, headers=headers)
    assert response.status_code == (403 if identity == "unassigned" else 401)
    if identity != "unassigned":
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("resource_id", [other_client, uuid4()])
@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("GET", "", None),
        ("PATCH", "", {"name": "Changed"}),
        ("GET", "/appointments", None),
    ],
)
def test_foreign_and_missing_clients_return_same_not_found(
    client: TestClient,
    database: Engine,
    resource_id: UUID,
    method: str,
    suffix: str,
    payload: dict | None,
) -> None:
    response = client.request(
        method,
        f"{base_url}/{resource_id}{suffix}",
        params={"business_id": str(business_b)},
        json=payload,
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Client not found"}
    with Session(database) as session:
        assert session.get(Client, other_client).name == "Foreign"


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("field", ["business_id", "id", "created_at", "password"])
def test_request_forbids_tenant_and_unexpected_fields(
    client: TestClient, method: str, field: str
) -> None:
    path = base_url if method == "POST" else f"{base_url}/{client_a}"
    response = client.request(
        method,
        path,
        json={**new_client, field: str(business_b)},
        headers=auth_headers(),
    )
    assert response.status_code == 422


@pytest.mark.parametrize("suffix", ["", f"/{client_a}/appointments"])
@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_invalid_pagination_is_rejected(
    client: TestClient, suffix: str, params: dict
) -> None:
    response = client.get(base_url + suffix, params=params, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        {"name": " "},
        {"name": "x" * 121},
        {"phone": "123"},
        {"phone": "1" * 14},
        {"phone": None},
        {"phone": 85999999999},
        {"email": "not-an-email"},
        {"notes": "x" * 2001},
    ],
)
def test_invalid_client_data_is_rejected(client: TestClient, change: dict) -> None:
    response = client.post(
        base_url, json={**new_client, **change}, headers=auth_headers()
    )
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["name", "phone"])
def test_partial_update_does_not_allow_null_required_fields(
    client: TestClient, field: str
) -> None:
    response = client.patch(
        f"{base_url}/{client_a}", json={field: None}, headers=auth_headers()
    )
    assert response.status_code == 422


def test_no_client_login_or_delete_route(client: TestClient, database: Engine) -> None:
    response = client.delete(f"{base_url}/{client_a}", headers=auth_headers())
    assert response.status_code == 405
    with Session(database) as session:
        assert session.get(Client, client_a) is not None
    paths = app.openapi()["paths"]
    assert not any("login" in path for path in paths if "/clients" in path)
    for method, path, _ in protected_routes:
        openapi_path = path.replace(str(client_a), "{client_id}")
        operation = paths[base_url + openapi_path][method.lower()]
        assert operation["security"] == [{"HTTPBearer": []}]
        assert all(
            parameter["name"] != "business_id"
            for parameter in operation.get("parameters", [])
        )


def test_history_scopes_phone_and_tenant_orders_and_paginates(
    client: TestClient, database: Engine
) -> None:
    now = datetime.now(UTC)
    identifiers = [uuid4() for _ in range(6)]
    with Session(database) as session:
        for index, identifier in enumerate(identifiers):
            foreign = index == 3
            session.add(
                Appointment(
                    id=identifier,
                    business_id=business_b if foreign else business_a,
                    professional_id=professional_b if foreign else professional_a,
                    service_id=service_b if foreign else service_a,
                    customer_name="Alice",
                    customer_phone="85977777777" if index == 4 else "85999999999",
                    starts_at=now + timedelta(days=index - 2),
                    ends_at=now + timedelta(days=index - 2, minutes=30),
                    status=(
                        AppointmentStatus.BLOCKED
                        if index == 5
                        else AppointmentStatus.CANCELLED
                        if index == 1
                        else AppointmentStatus.CONFIRMED
                    ),
                    source=AppointmentSource.ONLINE,
                )
            )
        session.commit()
    response = client.get(f"{base_url}/{client_a}/appointments", headers=auth_headers())
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        str(item) for item in identifiers[2::-1]
    ]
    assert all(item["business_id"] == str(business_a) for item in response.json())
    assert response.json()[1]["status"] == "CANCELLED"
    response = client.get(
        f"{base_url}/{client_a}/appointments",
        params={"offset": 1, "limit": 1, "business_id": str(business_b)},
        headers=auth_headers(),
    )
    assert [item["id"] for item in response.json()] == [str(identifiers[1])]
    # Reading the history does not alter or adopt any existing appointment.
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 6
        assert session.get(Appointment, identifiers[3]).business_id == business_b
    response = client.patch(
        f"{base_url}/{client_a}",
        json={"phone": new_client["phone"]},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    response = client.get(f"{base_url}/{client_a}/appointments", headers=auth_headers())
    assert response.json() == []
    with Session(database) as session:
        assert session.get(Appointment, identifiers[0]).customer_phone == "85999999999"


def test_history_for_client_without_appointments_is_empty(client: TestClient) -> None:
    response = client.get(f"{base_url}/{client_a}/appointments", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == []


def test_database_constraints_prevent_duplicates_and_orphan_businesses(
    database: Engine,
) -> None:
    with Session(database) as session:
        session.add(
            Client(name="Duplicate", business_id=business_a, phone="85999999999")
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        session.add(Client(name="Orphan", business_id=uuid4(), phone="85988887777"))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("failure", ["integrity", "unexpected"])
def test_commit_failure_rolls_back_and_allows_retry(
    client: TestClient, database: Engine, method: str, failure: str
) -> None:
    path = base_url if method == "POST" else f"{base_url}/{client_a}"
    error = (
        IntegrityError("private statement", {}, Exception("private database details"))
        if failure == "integrity"
        else RuntimeError("private database details")
    )
    with (
        patch.object(Session, "commit", side_effect=error),
        patch.object(
            Session, "rollback", autospec=True, side_effect=Session.rollback
        ) as rollback,
    ):
        response = client.request(method, path, json=new_client, headers=auth_headers())
        assert response.status_code == (409 if failure == "integrity" else 500)
        rollback.assert_called_once()
        assert "private" not in response.text
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Client)) == 3
        assert session.get(Client, client_a).name == "Alice"
    response = client.request(method, path, json=new_client, headers=auth_headers())
    assert response.status_code == (201 if method == "POST" else 200)


def test_repository_leaves_transaction_control_to_caller(database: Engine) -> None:
    with Session(database) as session:
        repository = ClientRepository(session)
        created = repository.create(ClientCreate(**new_client), business_id=business_a)
        assert created.id.version == 4
        repository.update(created, ClientUpdate(name="Changed"))
        session.rollback()
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Client)) == 3


def test_schema_preserves_partial_update_fields() -> None:
    assert ClientUpdate(email=None).model_dump(exclude_unset=True) == {"email": None}
    assert ClientUpdate().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        ClientCreate(**{**new_client, "business_id": business_a})


@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    [(ClientConflictError, 409), (ClientNotFoundError, 404), (ClientError, 500)],
)
def test_error_handler_supports_subclasses_and_hides_unexpected_details(
    client: TestClient, error_type: type[ClientError], expected_status: int
) -> None:
    error = type("SpecificClientError", (error_type,), {})("Error details")
    with patch.object(ClientService, "list", side_effect=error):
        response = client.get(base_url, headers=auth_headers())
    assert response.status_code == expected_status
    assert response.json()["detail"] == (
        "Internal server error" if expected_status == 500 else "Error details"
    )
