from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
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
from test_financial_categories import (
    category_root,
    expense_category_a,
    financial_categories,
    income_category_a,
    income_category_b,
)

from app.modules.financial_entries.models import FinancialEntry
from app.modules.recurring_entries.models import RecurringEntry

__all__ = ["client", "database", "financial_categories", "password_hash"]
root = "/api/v1/recurring-entries"
entries_root = "/api/v1/financial-entries"


def payload(**changes):
    return {
        "category_id": str(income_category_a),
        "type": "INCOME",
        "description": "  Monthly fee  ",
        "amount": "100.10",
        "due_day": 31,
        "start_date": "2026-01-01",
        **changes,
    }


def create_recurrence(client, headers=None, **changes):
    response = client.post(
        root, headers=headers or auth_headers(), json=payload(**changes)
    )
    assert response.status_code == 201, response.text
    return response.json()


def generate(client, recurrence_id, start="2026-01-01", end="2026-03-01", headers=None):
    return client.post(
        f"{root}/{recurrence_id}/generate",
        headers=headers or auth_headers(),
        json={"start_month": start, "end_month": end},
    )


@pytest.mark.parametrize(
    "entry_type,category_id",
    [("INCOME", income_category_a), ("EXPENSE", expense_category_a)],
)
def test_crud_and_suspension_preserve_recurrence_and_entries(
    client, database, entry_type, category_id
):
    data = create_recurrence(
        client, type=entry_type, category_id=str(category_id), end_date="2026-03-31"
    )
    assert UUID(data["id"]).version == 4
    assert data["business_id"] == str(business_a)
    assert data["description"] == "Monthly fee" and data["amount"] == "100.10"
    path = f"{root}/{data['id']}"
    assert client.get(path, headers=auth_headers()).json() == data
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(FinancialEntry)) == 0
        assert session.get(RecurringEntry, UUID(data["id"])).category.id == category_id
    original = generate(client, data["id"]).json()["created_entries"]
    assert len(original) == 3
    response = client.patch(
        path,
        headers=auth_headers(),
        json={"description": "Updated", "amount": "0.10", "end_date": None},
    )
    assert response.status_code == 200 and response.json()["end_date"] is None
    assert response.json()["amount"] == "0.10"
    assert client.delete(path, headers=auth_headers()).status_code == 204
    assert client.delete(path, headers=auth_headers()).status_code == 204
    assert client.get(path, headers=auth_headers()).json()["is_active"] is False
    assert generate(client, data["id"], "2026-04-01", "2026-04-01").status_code == 409
    with Session(database) as session:
        assert session.get(RecurringEntry, UUID(data["id"])).is_active is False
        stored = session.scalars(select(FinancialEntry)).all()
        assert len(stored) == 3
        assert all(item.amount == Decimal("100.10") for item in stored)
    assert (
        client.patch(path, headers=auth_headers(), json={"is_active": True}).status_code
        == 200
    )
    response = generate(client, data["id"], "2026-04-01", "2026-04-01")
    assert response.json()["created_entries"][0]["amount"] == "0.10"


def test_monthly_generation_is_idempotent_and_adjusts_short_months(client, database):
    recurrence = create_recurrence(client)
    first = generate(client, recurrence["id"])
    assert first.status_code == 200, first.text
    rows = first.json()["created_entries"]
    assert [item["due_date"] for item in rows] == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
    ]
    assert [item["competence"] for item in rows] == [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]
    assert all(
        item["status"] == "PENDING"
        and item["paid_at"] is None
        and item["appointment_id"] is None
        and item["recurring_entry_id"] == recurrence["id"]
        and item["business_id"] == str(business_a)
        for item in rows
    )
    second = generate(client, recurrence["id"], "2026-02-01", "2026-04-01").json()
    assert [item["due_date"] for item in second["created_entries"]] == ["2026-04-30"]
    assert second["skipped_competences"] == ["2026-02-01", "2026-03-01"]
    assert generate(client, recurrence["id"]).json()["created_entries"] == []
    with Session(database) as session:
        entry = session.get(FinancialEntry, UUID(rows[0]["id"]))
        assert entry.recurring_entry.id == UUID(recurrence["id"])
        assert len(entry.recurring_entry.entries) == 4
    listed = client.get(entries_root, headers=auth_headers()).json()
    assert {item["id"] for item in listed} == {
        item["id"] for item in rows + second["created_entries"]
    }


@pytest.mark.parametrize(
    "start,end,day,first,last,expected",
    [
        ("2024-02-01", "2024-02-01", 31, "2024-01-01", None, ["2024-02-29"]),
        ("2026-01-01", "2026-03-01", 15, "2026-01-16", "2026-03-14", ["2026-02-15"]),
        (
            "2026-01-01",
            "2026-03-01",
            15,
            "2026-01-15",
            "2026-03-15",
            ["2026-01-15", "2026-02-15", "2026-03-15"],
        ),
        ("2026-01-01", "2026-01-01", 1, "2026-02-01", None, []),
        ("2026-01-01", "2026-01-01", 31, "2026-01-01", "2026-01-30", []),
        (
            "2026-12-01",
            "2027-01-01",
            31,
            "2026-01-01",
            None,
            ["2026-12-31", "2027-01-31"],
        ),
        ("9999-12-01", "9999-12-01", 31, "9999-12-01", None, ["9999-12-31"]),
    ],
)
def test_due_dates_and_inclusive_recurrence_bounds(
    client, start, end, day, first, last, expected
):
    data = create_recurrence(client, due_day=day, start_date=first, end_date=last)
    response = generate(client, data["id"], start, end)
    assert response.status_code == 200, response.text
    assert [item["due_date"] for item in response.json()["created_entries"]] == expected


def test_edits_only_affect_new_competences_including_paid_and_cancelled_history(client):
    data = create_recurrence(client, start_date="2020-01-01")
    original = generate(client, data["id"], "2020-01-01", "2020-03-01").json()[
        "created_entries"
    ]
    paid_id, cancelled_id = original[0]["id"], original[1]["id"]
    paid = client.post(
        f"{entries_root}/{paid_id}/pay",
        headers=auth_headers(),
        json={"paid_at": "2020-02-01T12:00:00Z"},
    )
    assert paid.status_code == 200
    cancelled = client.patch(
        f"{entries_root}/{cancelled_id}",
        headers=auth_headers(),
        json={"status": "CANCELLED"},
    )
    assert cancelled.status_code == 200
    assert (
        client.patch(
            f"{root}/{data['id']}",
            headers=auth_headers(),
            json={
                "category_id": str(expense_category_a),
                "type": "EXPENSE",
                "amount": "999",
                "due_day": 10,
                "description": "New",
            },
        ).status_code
        == 200
    )
    result = generate(client, data["id"], "2020-01-01", "2020-04-01").json()
    assert len(result["created_entries"]) == 1
    assert result["skipped_competences"] == ["2020-01-01", "2020-02-01", "2020-03-01"]
    new = result["created_entries"][0]
    assert (
        new["type"] == "EXPENSE"
        and new["amount"] == "999.00"
        and new["due_date"] == "2020-04-10"
    )
    assert (
        client.get(f"{entries_root}/{paid_id}", headers=auth_headers()).json()
        == paid.json()
    )
    assert (
        client.get(f"{entries_root}/{cancelled_id}", headers=auth_headers()).json()
        == cancelled.json()
    )
    assert (
        client.get(f"{entries_root}/{original[2]['id']}", headers=auth_headers()).json()
        == original[2]
    )
    for entry_id in (paid_id, cancelled_id, original[2]["id"]):
        assert (
            client.delete(
                f"{entries_root}/{entry_id}", headers=auth_headers()
            ).status_code
            == 409
        )


def test_list_filters_and_pagination_use_authenticated_business(client):
    active = create_recurrence(client, description="A")
    inactive = create_recurrence(
        client,
        description="B",
        category_id=str(expense_category_a),
        type="EXPENSE",
        is_active=False,
    )
    foreign = create_recurrence(
        client, headers=auth_headers(owner_b), category_id=str(income_category_b)
    )

    def listing(**params):
        response = client.get(root, headers=auth_headers(), params=params)
        assert response.status_code == 200
        return [item["id"] for item in response.json()]

    assert listing(business_id=str(business_b)) == [active["id"], inactive["id"]]
    assert listing(is_active=True) == [active["id"]]
    assert listing(is_active=False) == [inactive["id"]]
    assert listing(type="EXPENSE") == [inactive["id"]]
    assert listing(category_id=str(expense_category_a)) == [inactive["id"]]
    assert listing(category_id=str(income_category_b)) == []
    assert listing(offset=1, limit=1) == [inactive["id"]]
    assert [
        item["id"] for item in client.get(root, headers=auth_headers(owner_b)).json()
    ] == [foreign["id"]]


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("POST", ""),
        ("GET", ""),
        ("GET", "/{id}"),
        ("PATCH", "/{id}"),
        ("DELETE", "/{id}"),
        ("POST", "/{id}/generate"),
    ],
)
@pytest.mark.parametrize(
    "identity,status",
    [(None, 401), ("invalid", 401), (inactive_user, 401), (unassigned_user, 403)],
)
def test_jwt_and_business_required_on_every_route(
    client, method, suffix, identity, status
):
    headers = (
        {}
        if identity is None
        else {"Authorization": "Bearer invalid"}
        if identity == "invalid"
        else auth_headers(identity)
    )
    response = client.request(
        method, root + suffix.format(id=uuid4()), headers=headers, json={}
    )
    assert response.status_code == status


def test_cross_business_ids_are_not_accessible_or_writable(client, database):
    foreign = create_recurrence(
        client, headers=auth_headers(owner_b), category_id=str(income_category_b)
    )
    for identifier in (foreign["id"], str(uuid4())):
        path = f"{root}/{identifier}"
        for method, suffix, body in [
            ("GET", "", None),
            ("PATCH", "", {"amount": "999"}),
            ("DELETE", "", None),
            (
                "POST",
                "/generate",
                {"start_month": "2026-01-01", "end_month": "2026-01-01"},
            ),
        ]:
            response = client.request(
                method, path + suffix, headers=auth_headers(), json=body
            )
            assert response.status_code == 404
            assert response.json() == {"detail": "Recurring entry not found"}
    with Session(database) as session:
        assert session.get(RecurringEntry, UUID(foreign["id"])).amount == Decimal(
            "100.10"
        )
        assert session.scalar(select(func.count()).select_from(FinancialEntry)) == 0


@pytest.mark.parametrize(
    "category_id,entry_type",
    [
        (income_category_b, "INCOME"),
        (uuid4(), "INCOME"),
        (expense_category_a, "INCOME"),
    ],
)
def test_invalid_category_tenant_and_type_on_create_and_update(
    client, category_id, entry_type
):
    assert (
        client.post(
            root,
            headers=auth_headers(),
            json=payload(category_id=str(category_id), type=entry_type),
        ).status_code
        == 422
    )
    own = create_recurrence(client)
    assert (
        client.patch(
            f"{root}/{own['id']}",
            headers=auth_headers(),
            json={"category_id": str(category_id), "type": entry_type},
        ).status_code
        == 422
    )
    assert client.get(f"{root}/{own['id']}", headers=auth_headers()).json() == own


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "0.001"},
        {"amount": "NaN"},
        {"amount": "Infinity"},
        {"amount": "10000000000.00"},
        {"description": " "},
        {"description": "x" * 501},
        {"due_day": 0},
        {"due_day": 32},
        {"due_day": 1.5},
        {"due_day": True},
        {"start_date": "bad"},
        {"end_date": "2025-12-31"},
        {"business_id": str(business_b)},
        {"id": str(uuid4())},
        {"paid_at": "2026-01-01"},
        {"status": "PAID"},
        {"frequency": "WEEKLY"},
    ],
)
def test_create_validation_and_mass_assignment(client, changes):
    assert (
        client.post(root, headers=auth_headers(), json=payload(**changes)).status_code
        == 422
    )


@pytest.mark.parametrize(
    "field",
    [
        "category_id",
        "type",
        "description",
        "amount",
        "due_day",
        "start_date",
        "is_active",
    ],
)
def test_patch_rejects_explicit_null_required_fields(client, field):
    data = create_recurrence(client)
    assert (
        client.patch(
            f"{root}/{data['id']}", headers=auth_headers(), json={field: None}
        ).status_code
        == 422
    )


def test_partial_date_updates_validate_against_stored_dates(client):
    data = create_recurrence(client, end_date="2026-12-31")
    path = f"{root}/{data['id']}"
    for changes in ({"start_date": "2027-01-01"}, {"end_date": "2025-12-31"}):
        assert (
            client.patch(path, headers=auth_headers(), json=changes).status_code == 422
        )
        assert client.get(path, headers=auth_headers()).json() == data
    assert client.patch(path, headers=auth_headers(), json={}).json() == data
    assert (
        client.patch(path, headers=auth_headers(), json={"end_date": None}).json()[
            "end_date"
        ]
        is None
    )


@pytest.mark.parametrize(
    "body",
    [
        {"start_month": "2026-02-01", "end_month": "2026-01-01"},
        {"start_month": "2026-01-01", "end_month": "2027-01-01"},
        {"start_month": "2026-01-02", "end_month": "2026-02-01"},
        {"start_month": "2026-01-01", "end_month": "2026-02-02"},
        {
            "start_month": "2026-01-01",
            "end_month": "2026-01-01",
            "business_id": str(business_b),
        },
    ],
)
def test_generation_period_validation(client, body):
    data = create_recurrence(client)
    assert (
        client.post(
            f"{root}/{data['id']}/generate", headers=auth_headers(), json=body
        ).status_code
        == 422
    )


def test_twelve_month_limit_and_inactive_create(client):
    data = create_recurrence(client, is_active=False)
    assert generate(client, data["id"]).status_code == 409
    assert (
        client.patch(
            f"{root}/{data['id']}", headers=auth_headers(), json={"is_active": True}
        ).status_code
        == 200
    )
    response = generate(client, data["id"], "2026-01-01", "2026-12-01")
    assert response.status_code == 200 and len(response.json()["created_entries"]) == 12


@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_list_pagination_validation(client, params):
    assert client.get(root, headers=auth_headers(), params=params).status_code == 422


def test_categories_referenced_by_inactive_recurrences_cannot_be_deleted_or_change_type(
    client,
):
    create_recurrence(client, is_active=False)
    path = f"{category_root}/{income_category_a}"
    assert client.delete(path, headers=auth_headers()).status_code == 409
    assert (
        client.patch(path, headers=auth_headers(), json={"type": "EXPENSE"}).status_code
        == 409
    )
    assert (
        client.patch(path, headers=auth_headers(), json={"name": "Renamed"}).status_code
        == 200
    )


def test_manual_entries_do_not_block_or_claim_recurring_competences(client):
    response = client.post(
        entries_root,
        headers=auth_headers(),
        json={
            "category_id": str(income_category_a),
            "type": "INCOME",
            "description": "Manual",
            "amount": "100",
            "due_date": "2026-01-31",
        },
    )
    assert response.status_code == 201
    assert (
        response.json()["recurring_entry_id"] is None
        and response.json()["competence"] is None
    )
    data = create_recurrence(client)
    assert len(generate(client, data["id"]).json()["created_entries"]) == 3
    for field, value in (
        ("recurring_entry_id", data["id"]),
        ("competence", "2026-01-01"),
    ):
        assert (
            client.patch(
                f"{entries_root}/{response.json()['id']}",
                headers=auth_headers(),
                json={field: value},
            ).status_code
            == 422
        )
