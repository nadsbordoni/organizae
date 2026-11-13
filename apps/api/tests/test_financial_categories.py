from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
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
    unassigned_user,
)

from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_categories.repository import FinancialCategoryRepository

__all__ = ["client", "database", "password_hash"]
income_category_a, expense_category_a, income_category_b = uuid4(), uuid4(), uuid4()
category_root = "/api/v1/financial-categories"


@pytest.fixture(autouse=True)
def financial_categories(database):
    with Session(database) as session:
        session.add_all(
            [
                FinancialCategory(
                    id=income_category_a,
                    business_id=business_a,
                    name="Vendas",
                    type=FinancialType.INCOME,
                ),
                FinancialCategory(
                    id=expense_category_a,
                    business_id=business_a,
                    name="Custos",
                    type=FinancialType.EXPENSE,
                ),
                FinancialCategory(
                    id=income_category_b,
                    business_id=business_b,
                    name="Vendas",
                    type=FinancialType.INCOME,
                ),
            ]
        )
        session.commit()


def test_financial_category_crud_and_type_update(client, database):
    response = client.post(
        category_root,
        headers=auth_headers(),
        json={"name": "  Outros  ", "type": "INCOME"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert UUID(data["id"]).version == 4
    assert data == {
        "id": data["id"],
        "business_id": str(business_a),
        "name": "Outros",
        "type": "INCOME",
    }
    path = f"{category_root}/{data['id']}"
    assert client.get(path, headers=auth_headers()).json() == data
    response = client.patch(
        path, headers=auth_headers(), json={"name": "Aluguel", "type": "EXPENSE"}
    )
    assert response.status_code == 200 and response.json()["type"] == "EXPENSE"
    assert client.patch(path, headers=auth_headers(), json={}).json() == response.json()
    response = client.delete(path, headers=auth_headers())
    assert response.status_code == 204 and response.content == b""
    assert client.get(path, headers=auth_headers()).status_code == 404
    with Session(database) as session:
        assert session.get(FinancialCategory, UUID(data["id"])) is None


@pytest.mark.parametrize("name", ["Vendas", "vendas", "  VENDAS  "])
def test_names_are_unique_per_business_and_type_case_insensitively(client, name):
    assert (
        client.post(
            category_root, headers=auth_headers(), json={"name": name, "type": "INCOME"}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"{category_root}/{expense_category_a}",
            headers=auth_headers(),
            json={"name": name, "type": "INCOME"},
        ).status_code
        == 409
    )


def test_same_name_can_be_used_for_other_type_or_other_business(client):
    response = client.post(
        category_root,
        headers=auth_headers(),
        json={"name": "Vendas", "type": "EXPENSE"},
    )
    assert response.status_code == 201
    for headers in (auth_headers(), auth_headers(owner_b)):
        response = client.post(
            category_root, headers=headers, json={"name": "Outros", "type": "INCOME"}
        )
        assert response.status_code == 201
    response = client.patch(
        f"{category_root}/{income_category_a}",
        headers=auth_headers(),
        json={"name": "vendas"},
    )
    assert response.status_code == 200


def test_listing_filters_type_paginates_and_ignores_client_business_id(client):
    response = client.get(
        category_root,
        headers=auth_headers(),
        params={"business_id": str(business_b), "limit": 1},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(expense_category_a)]
    response = client.get(
        category_root, headers=auth_headers(), params={"offset": 1, "limit": 1}
    )
    assert [item["id"] for item in response.json()] == [str(income_category_a)]
    response = client.get(
        category_root, headers=auth_headers(), params={"type": "INCOME"}
    )
    assert [item["id"] for item in response.json()] == [str(income_category_a)]
    response = client.get(category_root, headers=auth_headers(owner_b))
    assert [item["id"] for item in response.json()] == [str(income_category_b)]


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", category_root),
        ("GET", category_root),
        ("GET", f"{category_root}/{income_category_a}"),
        ("PATCH", f"{category_root}/{income_category_a}"),
        ("DELETE", f"{category_root}/{income_category_a}"),
    ],
)
@pytest.mark.parametrize(
    "identity,status",
    [(None, 401), ("invalid", 401), (inactive_user, 401), (unassigned_user, 403)],
)
def test_categories_require_active_jwt_and_business(
    client, method, path, identity, status
):
    headers = (
        {}
        if identity is None
        else {"Authorization": "Bearer invalid"}
        if identity == "invalid"
        else auth_headers(identity)
    )
    response = client.request(
        method, path, headers=headers, json={"name": "Changed", "type": "INCOME"}
    )
    assert response.status_code == status
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("category_id", [income_category_b, uuid4()])
def test_foreign_and_missing_categories_return_same_error(client, method, category_id):
    response = client.request(
        method,
        f"{category_root}/{category_id}",
        headers=auth_headers(),
        json={"name": "Changed"},
        params={"business_id": str(business_b)},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Financial category not found"}


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": " "},
        {"name": "a" * 151},
        {"type": None},
        {"type": "OTHER"},
        {"business_id": str(business_b)},
        {"id": str(uuid4())},
    ],
)
@pytest.mark.parametrize(
    "method,path",
    [("POST", category_root), ("PATCH", f"{category_root}/{income_category_a}")],
)
def test_invalid_category_fields_and_tenant_injection_are_rejected(
    client, payload, method, path
):
    data = {"name": "New", "type": "INCOME", **payload}
    assert (
        client.request(method, path, headers=auth_headers(), json=data).status_code
        == 422
    )


@pytest.mark.parametrize(
    "params", [{"offset": -1}, {"limit": 0}, {"limit": 101}, {"type": "OTHER"}]
)
def test_category_filter_validation(client, params):
    assert (
        client.get(category_root, headers=auth_headers(), params=params).status_code
        == 422
    )


def test_database_unique_constraint_handles_missed_precheck(client, database):
    with patch.object(FinancialCategoryRepository, "get_by_name", return_value=None):
        response = client.post(
            category_root,
            headers=auth_headers(),
            json={"name": "vendas", "type": "INCOME"},
        )
    assert response.status_code == 409
    with Session(database) as session:
        assert len(session.scalars(select(FinancialCategory)).all()) == 3
