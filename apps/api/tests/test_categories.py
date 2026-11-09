from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_clients import (
    auth_headers,
    business_a,
    business_b,
    client,
    database,
    inactive_user,
    owner_b,
    password_hash,
    service_a,
    service_b,
    unassigned_user,
)

from app.modules.business_categories.models import BusinessCategory
from app.modules.categories.exceptions import CategoryError, CategoryNotFoundError
from app.modules.categories.models import Category
from app.modules.categories.repository import CategoryRepository
from app.modules.services.models import Service
from app.modules.services.schemas import ServiceCreateRequest, ServiceUpdate

__all__ = ["client", "database", "password_hash"]
category_a, another_category, category_b = uuid4(), uuid4(), uuid4()
root = "/api/v1/categories"
service_root = "/api/v1/services"


@pytest.fixture(autouse=True)
def categories(database):
    with Session(database) as session:
        session.add_all(
            [
                Category(id=category_a, business_id=business_a, name="Cortes"),
                Category(id=another_category, business_id=business_a, name="Barba"),
                Category(id=category_b, business_id=business_b, name="Cortes"),
            ]
        )
        session.flush()
        session.get(Service, service_a).category_id = category_a
        session.get(Service, service_b).category_id = category_b
        session.commit()


def test_category_crud_uses_authenticated_business_and_serializes_uuid(
    client, database
):
    response = client.post(root, headers=auth_headers(), json={"name": "  Coloração  "})
    assert response.status_code == 201, response.text
    data = response.json()
    assert UUID(data["id"]).version == 4
    assert data == {
        "id": data["id"],
        "business_id": str(business_a),
        "name": "Coloração",
    }
    path = f"{root}/{data['id']}"
    assert client.get(path, headers=auth_headers()).json() == data
    updated = client.patch(path, headers=auth_headers(), json={"name": "  Produtos  "})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Produtos"
    assert client.patch(path, headers=auth_headers(), json={}).json() == updated.json()
    deleted = client.delete(path, headers=auth_headers())
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get(path, headers=auth_headers()).status_code == 404
    assert client.delete(path, headers=auth_headers()).status_code == 404
    with Session(database) as session:
        assert session.get(Category, UUID(data["id"])) is None
        assert session.get(BusinessCategory, 1).name == "Beauty"


def test_list_is_ordered_paginated_and_cannot_switch_business_by_query(client):
    response = client.get(
        root,
        headers=auth_headers(),
        params={"business_id": str(business_b), "limit": 1},
    )
    assert response.status_code == 200
    assert response.json() == [
        {"id": str(another_category), "business_id": str(business_a), "name": "Barba"}
    ]
    response = client.get(
        root, headers=auth_headers(), params={"offset": 1, "limit": 1}
    )
    assert [item["id"] for item in response.json()] == [str(category_a)]
    response = client.get(root, headers=auth_headers(owner_b))
    assert [item["id"] for item in response.json()] == [str(category_b)]


@pytest.mark.parametrize("name", ["Cortes", "cortes", "  CORTES  "])
def test_duplicate_names_in_same_business_are_rejected_for_create_and_update(
    client, name
):
    assert (
        client.post(root, headers=auth_headers(), json={"name": name}).status_code
        == 409
    )
    assert (
        client.patch(
            f"{root}/{another_category}", headers=auth_headers(), json={"name": name}
        ).status_code
        == 409
    )
    assert (
        client.get(f"{root}/{another_category}", headers=auth_headers()).json()["name"]
        == "Barba"
    )


def test_same_name_is_allowed_in_different_businesses_and_case_only_rename_is_valid(
    client,
):
    for headers in (auth_headers(), auth_headers(owner_b)):
        response = client.post(root, headers=headers, json={"name": "Produtos"})
        assert response.status_code == 201
    response = client.patch(
        f"{root}/{category_a}", headers=auth_headers(), json={"name": "cortes"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(category_a)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", root),
        ("GET", root),
        ("GET", f"{root}/{category_a}"),
        ("PATCH", f"{root}/{category_a}"),
        ("DELETE", f"{root}/{another_category}"),
    ],
)
@pytest.mark.parametrize(
    "identity,expected",
    [(None, 401), ("invalid", 401), (inactive_user, 401), (unassigned_user, 403)],
)
def test_all_category_routes_require_active_authenticated_business_user(
    client, method, path, identity, expected
):
    headers = (
        {}
        if identity is None
        else {"Authorization": "Bearer invalid"}
        if identity == "invalid"
        else auth_headers(identity)
    )
    response = client.request(method, path, headers=headers, json={"name": "Changed"})
    assert response.status_code == expected
    if expected == 401:
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("category_id", [category_b, uuid4()])
def test_foreign_and_missing_category_ids_are_indistinguishable(
    client, database, method, category_id
):
    response = client.request(
        method,
        f"{root}/{category_id}",
        headers=auth_headers(),
        params={"business_id": str(business_b)},
        json={"name": "Changed"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Category not found"}
    with Session(database) as session:
        assert session.get(Category, category_b).name == "Cortes"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": " "},
        {"name": "x" * 151},
        {"name": 10},
        {"name": "Changed", "business_id": str(business_b)},
        {"name": "Changed", "id": str(uuid4())},
    ],
)
@pytest.mark.parametrize(
    "method,path", [("POST", root), ("PATCH", f"{root}/{category_a}")]
)
def test_category_input_validation_forbids_identity_injection(
    client, payload, method, path
):
    assert (
        client.request(method, path, headers=auth_headers(), json=payload).status_code
        == 422
    )


@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_category_pagination_is_bounded(client, params):
    assert client.get(root, headers=auth_headers(), params=params).status_code == 422


def test_delete_linked_category_is_refused_until_service_is_unlinked(client, database):
    response = client.delete(f"{root}/{category_a}", headers=auth_headers())
    assert response.status_code == 409
    with Session(database) as session:
        assert session.get(Category, category_a) is not None
        assert session.get(Service, service_a).category_id == category_a
    response = client.patch(
        f"{service_root}/{service_a}",
        headers=auth_headers(),
        json={"category_id": None},
    )
    assert response.status_code == 200
    assert response.json()["category_id"] is None
    assert (
        client.delete(f"{root}/{category_a}", headers=auth_headers()).status_code == 204
    )
    with Session(database) as session:
        assert session.get(Service, service_a) is not None
        assert session.get(Service, service_b).category_id == category_b


def test_service_create_read_update_and_clear_category(client):
    payload = {
        "name": "Novo serviço",
        "price": "40.50",
        "duration_minutes": 30,
        "category_id": str(category_a),
    }
    response = client.post(service_root, headers=auth_headers(), json=payload)
    assert response.status_code == 201, response.text
    service_id = response.json()["id"]
    path = f"{service_root}/{service_id}"
    assert response.json()["category_id"] == str(category_a)
    assert client.get(path, headers=auth_headers()).json()["category_id"] == str(
        category_a
    )
    items = client.get(service_root, headers=auth_headers()).json()
    assert next(item for item in items if item["id"] == service_id)[
        "category_id"
    ] == str(category_a)
    response = client.patch(
        path, headers=auth_headers(), json={"category_id": str(another_category)}
    )
    assert response.status_code == 200
    assert response.json()["category_id"] == str(another_category)
    response = client.patch(path, headers=auth_headers(), json={"name": "Renamed"})
    assert response.json()["category_id"] == str(another_category)
    response = client.patch(path, headers=auth_headers(), json={"category_id": None})
    assert response.json()["category_id"] is None


def test_optional_category_preserves_existing_services_and_uncategorized_creation(
    client, database
):
    response = client.post(
        service_root,
        headers=auth_headers(),
        json={"name": "Sem categoria", "price": 10, "duration_minutes": 15},
    )
    assert response.status_code == 201
    assert response.json()["category_id"] is None
    assert (
        ServiceCreateRequest(name="Test", price=0, duration_minutes=1).category_id
        is None
    )
    assert ServiceUpdate().model_dump(exclude_unset=True) == {}
    assert ServiceUpdate(category_id=None).model_dump(exclude_unset=True) == {
        "category_id": None
    }
    with Session(database) as session:
        assert session.get(Service, UUID(response.json()["id"])).category is None


@pytest.mark.parametrize("category_id", [category_b, uuid4()])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_service_rejects_unknown_or_foreign_category_without_partial_writes(
    client, database, category_id, operation
):
    if operation == "create":
        response = client.post(
            service_root,
            headers=auth_headers(),
            json={
                "name": "Rejected",
                "price": 10,
                "duration_minutes": 30,
                "category_id": str(category_id),
            },
        )
    else:
        response = client.patch(
            f"{service_root}/{service_a}",
            headers=auth_headers(),
            json={"name": "Rejected", "category_id": str(category_id)},
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "Category not found in this business"}
    with Session(database) as session:
        assert session.scalar(select(Service).where(Service.name == "Rejected")) is None
        assert session.get(Service, service_a).category_id == category_a


@pytest.mark.parametrize(
    "category_id", ["invalid", 1, "6ba7b810-9dad-11d1-80b4-00c04fd430c8"]
)
def test_service_category_requires_uuid_v4(client, category_id):
    assert (
        client.patch(
            f"{service_root}/{service_a}",
            headers=auth_headers(),
            json={"category_id": category_id},
        ).status_code
        == 422
    )


def test_relationship_is_one_category_to_many_services_and_stays_in_business(database):
    with Session(database) as session:
        second = Service(
            business_id=business_a,
            name="Second",
            price=10,
            duration_minutes=15,
            category_id=category_a,
        )
        session.add(second)
        session.commit()
        category = session.get(Category, category_a)
        assert {service.id for service in category.services} == {service_a, second.id}
        assert all(
            service.business_id == category.business_id for service in category.services
        )
        assert second.category is category


def test_database_prevents_foreign_category_even_without_service_validation(database):
    with Session(database) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                update(Service)
                .where(Service.id == service_a)
                .values(category_id=category_b)
            )
        session.rollback()
        assert session.get(Service, service_a).category_id == category_a
        service = session.get(Service, service_a)
        service.category = session.get(Category, category_b)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert service.business_id == business_a


def test_database_prevents_deleting_used_category_even_when_collection_is_loaded(
    database,
):
    with Session(database) as session:
        category = session.get(Category, category_a)
        assert len(category.services) == 1
        session.delete(category)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(Service, service_a).category_id == category_a


def test_unique_index_handles_missed_precheck_and_rolls_back(client, database):
    with patch.object(CategoryRepository, "get_by_name", return_value=None):
        response = client.post(root, headers=auth_headers(), json={"name": "cortes"})
    assert response.status_code == 409
    with Session(database) as session:
        assert len(session.scalars(select(Category)).all()) == 3


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize(
    "failure,status",
    [
        (IntegrityError("private", {}, Exception("private")), 409),
        (RuntimeError("private"), 500),
    ],
)
def test_category_transactions_roll_back_on_failure(
    client, database, operation, failure, status
):
    original_rollback = Session.rollback
    with (
        patch.object(Session, "commit", side_effect=failure),
        patch.object(
            Session, "rollback", autospec=True, side_effect=original_rollback
        ) as rollback,
    ):
        if operation == "create":
            response = client.post(root, headers=auth_headers(), json={"name": "New"})
        elif operation == "update":
            response = client.patch(
                f"{root}/{another_category}",
                headers=auth_headers(),
                json={"name": "New"},
            )
        else:
            response = client.delete(
                f"{root}/{another_category}", headers=auth_headers()
            )
    assert response.status_code == status
    assert "private" not in response.text
    rollback.assert_called_once()
    with Session(database) as session:
        assert session.get(Category, another_category).name == "Barba"
        assert session.scalar(select(Category).where(Category.name == "New")) is None


def test_repository_never_commits_and_leaves_rollback_to_caller(database):
    with Session(database) as session:
        repository = CategoryRepository(session)
        from app.modules.categories.schemas import CategoryCreate, CategoryUpdate

        category = repository.create(
            CategoryCreate(name="Transient"), business_id=business_a
        )
        identifier = category.id
        repository.update(category, CategoryUpdate(name="Changed"))
        assert repository.get_by_id(identifier, business_id=business_b) is None
        assert (
            repository.get_by_name("changed", business_id=business_a).id == identifier
        )
        session.rollback()
        assert repository.get_by_id(identifier, business_id=business_a) is None
        category = repository.get_by_id(another_category, business_id=business_a)
        repository.delete(category)
        session.rollback()
        assert (
            repository.get_by_id(another_category, business_id=business_a) is not None
        )


@pytest.mark.parametrize(
    "error,expected",
    [
        (type("MissingCategory", (CategoryNotFoundError,), {}), 404),
        (CategoryError, 500),
    ],
)
def test_error_handler_supports_subclasses_and_hides_unexpected_details(
    client, error, expected
):
    with patch.object(CategoryRepository, "get_by_id", side_effect=error("private")):
        response = client.get(f"{root}/{category_a}", headers=auth_headers())
    assert response.status_code == expected
    if expected == 500:
        assert response.json() == {"detail": "Internal server error"}
