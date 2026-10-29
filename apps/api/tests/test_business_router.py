from collections.abc import Iterator
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

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

from app.modules.auth.dependencies import get_current_user
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
from app.modules.users.models import User

business_id = UUID("8ccacb20-1d36-44a7-9d32-08ac5f6bf15e")
business_path = f"/api/v1/businesses/{business_id}"
current_user_id = uuid4()


@pytest.fixture
def business() -> Business:
    return Business(
        id=business_id,
        name="Studio",
        category_id=1,
        whatsapp="85999999999",
        service_mode=ServiceMode.HIBRIDO,
    )


@pytest.fixture
def api_client(business: Business) -> Iterator[tuple[TestClient, Mock]]:
    service = Mock(spec=BusinessService)
    service.create_for_user.return_value = business
    service.get_by_id.return_value = business
    service.update.return_value = business
    service.list.return_value = [business]
    app.dependency_overrides[get_business_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id=current_user_id, business_id=business_id, is_active=True
    )
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        app.dependency_overrides.pop(get_business_service)
        app.dependency_overrides.pop(get_current_user)


def test_create_business(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    payload = {
        "name": "Studio",
        "category_id": 1,
        "whatsapp": "85999999999",
        "service_mode": "HIBRIDO",
    }
    response = client.post("/api/v1/businesses", json=payload)

    assert response.status_code == 201
    assert response.json() == {
        **payload,
        "id": str(business_id),
        "logo_url": None,
        "description": None,
        "external_link": None,
        "address": None,
    }
    service.create_for_user.assert_called_once_with(
        BusinessCreate(**payload), user_id=current_user_id
    )


@pytest.mark.parametrize(
    "query, offset, limit", [("", 0, 100), ("?offset=10&limit=5", 10, 5)]
)
def test_list_businesses(
    api_client: tuple[TestClient, Mock], query: str, offset: int, limit: int
) -> None:
    client, service = api_client
    response = client.get(f"/api/v1/businesses{query}")
    assert response.status_code == 200
    assert response.json()[0]["id"] == str(business_id)
    service.list.assert_called_once_with(
        business_id=business_id, offset=offset, limit=limit
    )


def test_list_empty_businesses(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    service.list.return_value = []
    response = client.get("/api/v1/businesses")
    assert response.status_code == 200
    assert response.json() == []


def test_get_business(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    response = client.get(business_path)
    assert response.status_code == 200
    assert response.json()["id"] == str(business_id)
    service.get_by_id.assert_called_once_with(business_id)


@pytest.mark.parametrize("payload", [{"name": "Updated"}, {"description": None}, {}])
def test_update_business(
    api_client: tuple[TestClient, Mock], payload: dict[str, str | None]
) -> None:
    client, service = api_client
    response = client.patch(business_path, json=payload)
    assert response.status_code == 200
    service.update.assert_called_once_with(business_id, BusinessUpdate(**payload))
    assert service.update.call_args.args[1].model_dump(exclude_unset=True) == payload


def test_delete_business(api_client: tuple[TestClient, Mock]) -> None:
    client, service = api_client
    response = client.delete(business_path)
    assert response.status_code == 204
    assert response.content == b""
    service.delete.assert_called_once_with(business_id)


@pytest.mark.parametrize(
    "method, path, operation, error, expected_status",
    [
        ("GET", business_path, "get_by_id", BusinessNotFoundError, 404),
        ("PATCH", business_path, "update", BusinessNotFoundError, 404),
        ("DELETE", business_path, "delete", BusinessNotFoundError, 404),
        (
            "POST",
            "/api/v1/businesses",
            "create_for_user",
            BusinessCategoryNotFoundError,
            422,
        ),
        ("PATCH", business_path, "update", BusinessCategoryNotFoundError, 422),
        ("POST", "/api/v1/businesses", "create_for_user", BusinessConflictError, 409),
        ("PATCH", business_path, "update", BusinessConflictError, 409),
        ("DELETE", business_path, "delete", BusinessConflictError, 409),
        ("GET", "/api/v1/businesses", "list", InvalidBusinessPaginationError, 422),
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
        "service_mode": "HIBRIDO",
    }
    response = client.request(method, path, json=payload)
    assert response.status_code == expected_status
    assert response.json() == {"detail": "Business error"}


@pytest.mark.parametrize(
    "method, path, payload",
    [
        ("GET", "/api/v1/businesses/0", None),
        ("GET", "/api/v1/businesses/1", None),
        ("GET", "/api/v1/businesses/invalid", None),
        ("GET", "/api/v1/businesses/6ba7b810-9dad-11d1-80b4-00c04fd430c8", None),
        ("PATCH", "/api/v1/businesses/-1", {}),
        ("DELETE", "/api/v1/businesses/0", None),
        ("GET", "/api/v1/businesses?offset=-1", None),
        ("GET", "/api/v1/businesses?limit=0", None),
        ("GET", "/api/v1/businesses?limit=invalid", None),
        ("POST", "/api/v1/businesses", {}),
        ("POST", "/api/v1/businesses", {"name": " "}),
        ("PATCH", business_path, {"name": None}),
        ("PATCH", business_path, {"category_id": 0}),
        ("PATCH", business_path, {"service_mode": "invalid"}),
        ("PATCH", business_path, {"unknown": "value"}),
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
