from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
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
    from app.main import app
    from app.modules.services.route import get_service_service

from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.services.exceptions import (
    InvalidServicePaginationError,
    ServiceConflictError,
    ServiceError,
    ServiceNotFoundError,
)
from app.modules.services.models import Service
from app.modules.services.schemas import ServiceCreate, ServiceUpdate
from app.modules.services.service import ServiceService

business_id = uuid4()
service_id = uuid4()
base_path = "/api/v1/services"
service_path = f"{base_path}/{service_id}"
business_query = {"business_id": str(business_id)}


@pytest.fixture
def service_payload() -> dict[str, object]:
    return {
        "business_id": str(business_id),
        "name": "Haircut",
        "price": "25.50",
        "duration_minutes": 30,
    }


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, Mock]]:
    entity = Service(
        id=service_id,
        business_id=business_id,
        name="Haircut",
        price=Decimal("25.50"),
        duration_minutes=30,
        description=None,
        is_active=True,
    )
    service = Mock(spec=ServiceService)
    service.create.return_value = entity
    service.get_by_id.return_value = entity
    service.update.return_value = entity
    service.list.return_value = [entity]
    app.dependency_overrides[get_service_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        app.dependency_overrides.pop(get_service_service)


def test_create_service(
    api_client: tuple[TestClient, Mock], service_payload: dict[str, object]
) -> None:
    client, service = api_client
    response = client.post(base_path, json=service_payload)
    assert response.status_code == 201
    assert response.json() == {
        **service_payload,
        "id": str(service_id),
        "description": None,
        "is_active": True,
    }
    service.create.assert_called_once_with(ServiceCreate(**service_payload))


@pytest.mark.parametrize("pagination", [{}, {"offset": 10, "limit": 5}])
def test_list_services(
    api_client: tuple[TestClient, Mock], pagination: dict[str, int]
) -> None:
    client, service = api_client
    response = client.get(base_path, params={**business_query, **pagination})
    assert response.status_code == 200
    assert response.json()[0]["business_id"] == str(business_id)
    assert response.json()[0]["id"] == str(service_id)
    service.list.assert_called_once_with(
        business_id=business_id,
        offset=pagination.get("offset", 0),
        limit=pagination.get("limit", 100),
    )


def test_list_empty_services(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    service.list.return_value = []
    response = client.get(base_path, params=business_query)
    assert response.status_code == 200
    assert response.json() == []


def test_get_service(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    response = client.get(service_path, params=business_query)
    assert response.status_code == 200
    assert response.json()["id"] == str(service_id)
    service.get_by_id.assert_called_once_with(service_id, business_id=business_id)


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Updated"},
        {"description": None},
        {"is_active": False},
        {"price": "0"},
        {},
    ],
)
def test_partial_update(
    api_client: tuple[TestClient, Mock], payload: dict[str, object]
) -> None:
    client, service = api_client
    response = client.patch(service_path, params=business_query, json=payload)
    assert response.status_code == 200
    service.update.assert_called_once_with(
        service_id,
        ServiceUpdate(**payload),
        business_id=business_id,
    )
    expected = ServiceUpdate(**payload).model_dump(exclude_unset=True)
    assert service.update.call_args.args[1].model_dump(exclude_unset=True) == expected


def test_delete_service_returns_no_content(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    response = client.delete(service_path, params=business_query)
    assert response.status_code == 204
    assert response.content == b""
    service.delete.assert_called_once_with(service_id, business_id=business_id)


@pytest.mark.parametrize(
    "method, path, operation, error, expected_status",
    [
        ("POST", base_path, "create", BusinessNotFoundError, 404),
        ("POST", base_path, "create", ServiceConflictError, 409),
        ("GET", service_path, "get_by_id", ServiceNotFoundError, 404),
        ("PATCH", service_path, "update", ServiceNotFoundError, 404),
        ("DELETE", service_path, "delete", ServiceNotFoundError, 404),
        ("PATCH", service_path, "update", ServiceConflictError, 409),
        ("DELETE", service_path, "delete", ServiceConflictError, 409),
        ("GET", base_path, "list", InvalidServicePaginationError, 422),
    ],
)
def test_business_errors_map_to_http_responses(
    api_client: tuple[TestClient, Mock],
    service_payload: dict[str, object],
    method: str,
    path: str,
    operation: str,
    error: type[Exception],
    expected_status: int,
) -> None:
    client, service = api_client
    getattr(service, operation).side_effect = error("Business error")
    payload = service_payload if method == "POST" else {}
    response = client.request(method, path, params=business_query, json=payload)
    assert response.status_code == expected_status
    assert response.json() == {"detail": "Business error"}


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", base_path),
        ("GET", service_path),
        ("PATCH", service_path),
        ("DELETE", service_path),
    ],
)
@pytest.mark.parametrize(
    "query",
    [
        {},
        {"business_id": "invalid"},
        {"business_id": "1"},
        {"business_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"},
    ],
)
def test_missing_or_invalid_business_id_does_not_call_service(
    api_client: tuple[TestClient, Mock], method: str, path: str, query: dict[str, str]
) -> None:
    client, service = api_client
    response = client.request(method, path, params=query, json={})
    assert response.status_code == 422
    assert service.mock_calls == []


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "identifier", ["invalid", "1", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"]
)
def test_invalid_service_id_does_not_call_service(
    api_client: tuple[TestClient, Mock], method: str, identifier: str
) -> None:
    client, service = api_client
    response = client.request(
        method, f"{base_path}/{identifier}", params=business_query, json={}
    )
    assert response.status_code == 422
    assert service.mock_calls == []


@pytest.mark.parametrize(
    "pagination", [{"offset": -1}, {"limit": 0}, {"limit": 101}, {"limit": "invalid"}]
)
def test_invalid_pagination_does_not_call_service(
    api_client: tuple[TestClient, Mock], pagination: dict[str, object]
) -> None:
    client, service = api_client
    response = client.get(base_path, params={**business_query, **pagination})
    assert response.status_code == 422
    service.list.assert_not_called()


@pytest.mark.parametrize("method, path", [("POST", base_path), ("PATCH", service_path)])
@pytest.mark.parametrize(
    "field, value",
    [
        ("price", "-1"),
        ("price", "1.001"),
        ("duration_minutes", 0),
        ("duration_minutes", 1441),
        ("name", " "),
        ("is_active", None),
        ("id", str(uuid4())),
    ],
)
def test_invalid_payload_does_not_call_service(
    api_client: tuple[TestClient, Mock],
    service_payload: dict[str, object],
    method: str,
    path: str,
    field: str,
    value: object,
) -> None:
    client, service = api_client
    payload = {**service_payload, field: value} if method == "POST" else {field: value}
    response = client.request(method, path, params=business_query, json=payload)
    assert response.status_code == 422
    assert service.mock_calls == []


def test_update_cannot_change_business(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    response = client.patch(
        service_path, params=business_query, json={"business_id": str(uuid4())}
    )
    assert response.status_code == 422
    service.update.assert_not_called()


def test_create_requires_business_id(
    api_client: tuple[TestClient, Mock], service_payload: dict[str, object]
) -> None:
    client, service = api_client
    service_payload.pop("business_id")
    response = client.post(base_path, json=service_payload)
    assert response.status_code == 422
    service.create.assert_not_called()


def test_unknown_service_error_does_not_expose_details(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, service = api_client
    service.get_by_id.side_effect = ServiceError("sensitive internal detail")
    response = client.get(service_path, params=business_query)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


@pytest.mark.parametrize(
    "error_type, expected_status",
    [
        (ServiceNotFoundError, 404),
        (ServiceConflictError, 409),
        (InvalidServicePaginationError, 422),
    ],
)
def test_error_subclasses_use_registered_handler(
    api_client: tuple[TestClient, Mock],
    error_type: type[ServiceError],
    expected_status: int,
) -> None:
    client, service = api_client
    specialized_error = type("SpecializedError", (error_type,), {})
    nested_error = type("NestedError", (specialized_error,), {})
    service.get_by_id.side_effect = nested_error("Business error")

    response = client.get(service_path, params=business_query)

    assert response.status_code == expected_status
    assert response.json() == {"detail": "Business error"}


def test_unknown_error_subclass_does_not_expose_details(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, service = api_client
    unknown_error = type("UnknownError", (ServiceError,), {})
    service.get_by_id.side_effect = unknown_error("sensitive internal detail")

    response = client.get(service_path, params=business_query)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_service_dependency_uses_injected_session() -> None:
    session = Mock(spec=Session)
    service = get_service_service(session)
    assert service.session is session
    assert service.repository.session is session
    assert service.business_repository.session is session
