from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Import the app with test settings; no connection is opened by create_engine.
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
    from app.modules.businesses.router import get_business_service

from app.modules.businesses.exceptions import (
    BusinessCategoryNotFoundError,
    BusinessConflictError,
    BusinessError,
    BusinessNotFoundError,
    InvalidBusinessPaginationError,
)
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.schemas import BusinessCreate, BusinessUpdate
from app.modules.businesses.service import BusinessService


@pytest.fixture
def business() -> Business:
    return Business(
        id=1,
        name="Studio",
        category_id=1,
        whatsapp="85999999999",
        service_mode=ServiceMode.BOTH,
    )


@pytest.fixture
def api_client(business: Business) -> Iterator[tuple[TestClient, Mock]]:
    service = Mock(spec=BusinessService)
    service.create.return_value = business
    service.get_by_id.return_value = business
    service.update.return_value = business
    service.list.return_value = [business]
    app.dependency_overrides[get_business_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        app.dependency_overrides.pop(get_business_service)


def test_create_business(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    payload = {
        "name": "Studio",
        "category_id": 1,
        "whatsapp": "85999999999",
        "service_mode": "both",
    }
    response = client.post("/businesses", json=payload)

    assert response.status_code == 201
    assert response.json() == {
        **payload,
        "id": 1,
        "logo_url": None,
        "description": None,
        "external_link": None,
        "address": None,
    }
    service.create.assert_called_once_with(BusinessCreate(**payload))


@pytest.mark.parametrize(
    "query, offset, limit", [("", 0, 100), ("?offset=10&limit=5", 10, 5)]
)
def test_list_businesses(
    api_client: tuple[TestClient, Mock], query: str, offset: int, limit: int
) -> None:
    client, service = api_client
    response = client.get(f"/businesses{query}")
    assert response.status_code == 200
    assert response.json()[0]["id"] == 1
    service.list.assert_called_once_with(offset=offset, limit=limit)


def test_list_empty_businesses(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    service.list.return_value = []
    response = client.get("/businesses")
    assert response.status_code == 200
    assert response.json() == []


def test_get_business(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    response = client.get("/businesses/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1
    service.get_by_id.assert_called_once_with(1)


@pytest.mark.parametrize("payload", [{"name": "Updated"}, {"description": None}, {}])
def test_update_business(
    api_client: tuple[TestClient, Mock], payload: dict[str, str | None]
) -> None:
    client, service = api_client
    response = client.patch("/businesses/1", json=payload)
    assert response.status_code == 200
    service.update.assert_called_once_with(1, BusinessUpdate(**payload))
    assert service.update.call_args.args[1].model_dump(exclude_unset=True) == payload


def test_delete_business(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    response = client.delete("/businesses/1")
    assert response.status_code == 204
    assert response.content == b""
    service.delete.assert_called_once_with(1)


@pytest.mark.parametrize(
    "method, path, operation, error, expected_status",
    [
        ("GET", "/businesses/1", "get_by_id", BusinessNotFoundError, 404),
        ("PATCH", "/businesses/1", "update", BusinessNotFoundError, 404),
        ("DELETE", "/businesses/1", "delete", BusinessNotFoundError, 404),
        ("POST", "/businesses", "create", BusinessCategoryNotFoundError, 422),
        ("PATCH", "/businesses/1", "update", BusinessCategoryNotFoundError, 422),
        ("POST", "/businesses", "create", BusinessConflictError, 409),
        ("PATCH", "/businesses/1", "update", BusinessConflictError, 409),
        ("DELETE", "/businesses/1", "delete", BusinessConflictError, 409),
        ("GET", "/businesses", "list", InvalidBusinessPaginationError, 422),
    ],
)
def test_business_errors_map_to_http_responses(
    api_client: tuple[TestClient, Mock],
    method: str,
    path: str,
    operation: str,
    error: type[BusinessError],
    expected_status: int,
) -> None:
    client, service = api_client
    getattr(service, operation).side_effect = error("Business error")
    payload = {
        "name": "Studio",
        "category_id": 1,
        "whatsapp": "85999999999",
        "service_mode": "both",
    }
    response = client.request(method, path, json=payload)
    assert response.status_code == expected_status
    assert response.json() == {"detail": "Business error"}


@pytest.mark.parametrize(
    "method, path, payload",
    [
        ("GET", "/businesses/0", None),
        ("GET", "/businesses/invalid", None),
        ("PATCH", "/businesses/-1", {}),
        ("DELETE", "/businesses/0", None),
        ("GET", "/businesses?offset=-1", None),
        ("GET", "/businesses?limit=0", None),
        ("GET", "/businesses?limit=invalid", None),
        ("POST", "/businesses", {}),
        ("POST", "/businesses", {"name": " "}),
        ("PATCH", "/businesses/1", {"name": None}),
        ("PATCH", "/businesses/1", {"category_id": 0}),
        ("PATCH", "/businesses/1", {"service_mode": "invalid"}),
        ("PATCH", "/businesses/1", {"unknown": "value"}),
    ],
)
def test_invalid_requests_do_not_call_service(
    api_client: tuple[TestClient, Mock],
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    client, service = api_client
    response = client.request(method, path, json=payload)
    assert response.status_code == 422
    assert service.mock_calls == []


@pytest.mark.parametrize("failure", [False, True])
def test_session_dependency_closes_session(failure: bool) -> None:
    with patch.object(Session, "close", autospec=True) as close:
        dependency = get_db()
        session = next(dependency)
        if failure:
            with pytest.raises(RuntimeError, match="request failed"):
                dependency.throw(RuntimeError("request failed"))
        else:
            with pytest.raises(StopIteration):
                next(dependency)
        close.assert_called_once_with(session)


def test_service_dependency_uses_injected_session() -> None:
    session = Mock(spec=Session)
    service = get_business_service(session)
    assert service.session is session
    assert service.repository.session is session


def test_health_endpoint_is_preserved(api_client: tuple[TestClient, Mock]) -> None:
    client, _ = api_client
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
