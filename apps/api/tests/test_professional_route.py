from collections.abc import Iterator
from decimal import Decimal
from sqlite3 import Connection
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
    from app.db.session import get_db
    from app.main import app
    from app.modules.professionals.route import get_professional_service

from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.exceptions import (
    InvalidProfessionalPaginationError,
    InvalidProfessionalServicesError,
    ProfessionalConflictError,
    ProfessionalError,
    ProfessionalNotFoundError,
)
from app.modules.professionals.service import ProfessionalService
from app.modules.services.models import Service

business_id, other_business_id = uuid4(), uuid4()
first_service_id, second_service_id, other_service_id = uuid4(), uuid4(), uuid4()
base_path = "/api/v1/professionals"
business_query = {"business_id": str(business_id)}


@pytest.fixture
def client() -> Iterator[TestClient]:
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

    def get_test_db() -> Iterator[Session]:
        with Session(engine, autoflush=False, expire_on_commit=True) as session:
            yield session

    try:
        # Never connect to application databases in HTTP integration tests.
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
            session.add_all(
                [
                    Service(
                        id=identifier,
                        business_id=owner,
                        name=str(index),
                        price=Decimal("25.50"),
                        duration_minutes=30,
                    )
                    for index, (identifier, owner) in enumerate(
                        (
                            (first_service_id, business_id),
                            (second_service_id, business_id),
                            (other_service_id, other_business_id),
                        )
                    )
                ]
            )
            session.commit()
        app.dependency_overrides[get_db] = get_test_db
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture
def payload() -> dict[str, object]:
    return {
        "business_id": str(business_id),
        "name": "Professional",
        "phone": "85999999999",
        "service_ids": [str(first_service_id)],
    }


@pytest.fixture
def professional_path(client: TestClient, payload: dict[str, object]) -> str:
    response = client.post(base_path, json=payload)
    assert response.status_code == 201
    assert response.json()["services"][0]["id"] == str(first_service_id)
    return f"{base_path}/{response.json()['id']}"


def test_complete_crud_and_replacement(
    client: TestClient, professional_path: str
) -> None:
    response = client.get(professional_path, params=business_query)
    assert response.status_code == 200
    assert response.json()["is_active"] is True
    response = client.get(base_path, params=business_query)
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert (
        client.get(base_path, params={**business_query, "offset": 1, "limit": 1}).json()
        == []
    )
    assert (
        client.get(base_path, params={"business_id": str(other_business_id)}).json()
        == []
    )
    response = client.patch(
        professional_path,
        params=business_query,
        json={"name": "Updated", "phone": None},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated"
    assert response.json()["phone"] is None
    assert response.json()["services"][0]["id"] == str(first_service_id)
    for _ in range(2):
        response = client.put(
            f"{professional_path}/services",
            params=business_query,
            json={"service_ids": [str(second_service_id)]},
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["services"]] == [
            str(second_service_id)
        ]
    for _ in range(2):
        response = client.delete(professional_path, params=business_query)
        assert response.status_code == 204
        assert response.content == b""
    response = client.get(professional_path, params=business_query)
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["services"][0]["id"] == str(second_service_id)
    response = client.put(
        f"{professional_path}/services", params=business_query, json={"service_ids": []}
    )
    assert response.status_code == 200
    assert response.json()["services"] == []


@pytest.mark.parametrize("is_active", [None, True, False])
def test_list_filters_status_before_pagination_and_keeps_soft_deleted_links(
    client: TestClient, payload: dict[str, object], is_active: bool | None
) -> None:
    identifiers = []
    for index in range(4):
        response = client.post(base_path, json={**payload, "name": str(index)})
        assert response.status_code == 201
        identifiers.append(response.json()["id"])
    identifiers.sort()
    for identifier in identifiers[1::2]:
        path = f"{base_path}/{identifier}"
        assert client.delete(path, params=business_query).status_code == 204
        response = client.get(path, params=business_query)
        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert response.json()["services"][0]["id"] == str(first_service_id)
    for status in (True, False):
        response = client.post(
            base_path,
            json={
                **payload,
                "business_id": str(other_business_id),
                "service_ids": [str(other_service_id)],
                "is_active": status,
            },
        )
        assert response.status_code == 201
    query = dict(business_query)
    if is_active is not None:
        query["is_active"] = str(is_active).lower()
    expected_ids = (
        identifiers
        if is_active is None
        else identifiers[::2]
        if is_active
        else identifiers[1::2]
    )

    response = client.get(base_path, params=query)
    assert response.status_code == 200
    assert [professional["id"] for professional in response.json()] == expected_ids
    assert all(
        professional["business_id"] == str(business_id)
        for professional in response.json()
    )
    assert all(
        professional["services"][0]["id"] == str(first_service_id)
        for professional in response.json()
    )
    page = client.get(base_path, params={**query, "offset": 1, "limit": 1})
    assert page.status_code == 200
    assert [professional["id"] for professional in page.json()] == expected_ids[1:2]


@pytest.mark.parametrize("is_active", ["invalid", "", "null"])
def test_invalid_status_filter_is_rejected(client: TestClient, is_active: str) -> None:
    response = client.get(base_path, params={**business_query, "is_active": is_active})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "method, suffix", [("GET", ""), ("PATCH", ""), ("PUT", "/services"), ("DELETE", "")]
)
def test_existing_other_business_cannot_read_or_mutate_professional(
    client: TestClient, professional_path: str, method: str, suffix: str
) -> None:
    payload = {"service_ids": []} if method == "PUT" else {"name": "Wrong"}
    response = client.request(
        method,
        f"{professional_path}{suffix}",
        params={"business_id": str(other_business_id)},
        json=payload,
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Professional not found"}
    original = client.get(professional_path, params=business_query).json()
    assert original["name"] == "Professional"
    assert original["is_active"] is True
    assert original["services"][0]["id"] == str(first_service_id)


@pytest.mark.parametrize("operation", ["create", "replace"])
@pytest.mark.parametrize(
    "invalid_ids",
    [
        [str(second_service_id), str(other_service_id)],
        [str(second_service_id), str(uuid4())],
        [str(first_service_id), str(first_service_id).upper()],
    ],
)
def test_invalid_associations_do_not_change_existing_links(
    client: TestClient,
    professional_path: str,
    payload: dict[str, object],
    operation: str,
    invalid_ids: list[str],
) -> None:
    if operation == "create":
        response = client.post(base_path, json={**payload, "service_ids": invalid_ids})
    else:
        response = client.put(
            f"{professional_path}/services",
            params=business_query,
            json={"service_ids": invalid_ids},
        )
    assert response.status_code == 422
    assert len(client.get(base_path, params=business_query).json()) == 1
    original = client.get(professional_path, params=business_query).json()
    assert [item["id"] for item in original["services"]] == [str(first_service_id)]


def test_create_requires_existing_business(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post(base_path, json={**payload, "business_id": str(uuid4())})
    assert response.status_code == 404
    assert response.json() == {"detail": "Business not found"}
    assert client.get(base_path, params=business_query).json() == []


@pytest.mark.parametrize(
    "method, suffix",
    [("GET", None), ("GET", ""), ("PATCH", ""), ("PUT", "/services"), ("DELETE", "")],
)
@pytest.mark.parametrize(
    "query",
    [{}, {"business_id": "1"}, {"business_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"}],
)
def test_business_id_is_required_and_must_be_uuid4(
    client: TestClient,
    professional_path: str,
    method: str,
    suffix: str | None,
    query: dict[str, str],
) -> None:
    path = base_path if suffix is None else f"{professional_path}{suffix}"
    response = client.request(
        method, path, params=query, json={"service_ids": []} if method == "PUT" else {}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "method, suffix", [("GET", ""), ("PATCH", ""), ("PUT", "/services"), ("DELETE", "")]
)
@pytest.mark.parametrize("identifier", ["1", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"])
def test_professional_id_must_be_uuid4(
    client: TestClient, method: str, suffix: str, identifier: str
) -> None:
    response = client.request(
        method,
        f"{base_path}/{identifier}{suffix}",
        params=business_query,
        json={"service_ids": []} if method == "PUT" else {},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("pagination", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_pagination_limits(client: TestClient, pagination: dict[str, int]) -> None:
    assert (
        client.get(base_path, params={**business_query, **pagination}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "invalid_payload",
    [{}, {"service_ids": None}, {"service_ids": [], "business_id": str(uuid4())}],
)
def test_put_requires_complete_service_list(
    client: TestClient, professional_path: str, invalid_payload: dict[str, object]
) -> None:
    response = client.put(
        f"{professional_path}/services", params=business_query, json=invalid_payload
    )
    assert response.status_code == 422
    original = client.get(professional_path, params=business_query).json()
    assert original["services"][0]["id"] == str(first_service_id)


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"service_ids": []},
        {"business_id": str(uuid4())},
        {"name": None},
        {"is_active": None},
    ],
)
def test_patch_cannot_change_ownership_or_links_and_rejects_invalid_nulls(
    client: TestClient, professional_path: str, invalid_payload: dict[str, object]
) -> None:
    assert (
        client.patch(
            professional_path, params=business_query, json=invalid_payload
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "error_type, status_code",
    [
        (ProfessionalNotFoundError, 404),
        (ProfessionalConflictError, 409),
        (InvalidProfessionalServicesError, 422),
        (InvalidProfessionalPaginationError, 422),
        (ProfessionalError, 500),
    ],
)
def test_registered_handler_supports_subclasses_and_hides_unknown_error_details(
    client: TestClient, error_type: type[ProfessionalError], status_code: int
) -> None:
    nested_error = type("NestedError", (type("SpecificError", (error_type,), {}),), {})
    service = Mock(spec=ProfessionalService)
    service.get_by_id.side_effect = nested_error("Business error")
    app.dependency_overrides[get_professional_service] = lambda: service
    try:
        response = client.get(f"{base_path}/{uuid4()}", params=business_query)
        assert response.status_code == status_code
        assert response.json() == {
            "detail": "Internal server error"
            if status_code == 500
            else "Business error"
        }
    finally:
        app.dependency_overrides.pop(get_professional_service)


def test_service_dependency_uses_same_session() -> None:
    session = Mock(spec=Session)
    service = get_professional_service(session)
    assert service.session is session
    assert service.repository.session is session
    assert service.business_repository.session is session
    assert service.service_repository.session is session
