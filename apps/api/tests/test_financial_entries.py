from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session
from test_clients import (
    auth_headers,
    business_a,
    business_b,
    client,
    database,
    owner_b,
    password_hash,
    professional_a,
    professional_b,
    service_a,
    service_b,
)
from test_financial_categories import (
    category_root,
    expense_category_a,
    financial_categories,
    income_category_a,
    income_category_b,
)

from app.core.config import settings
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    BusinessHour,
)
from app.modules.financial_categories.models import FinancialCategory
from app.modules.financial_entries.models import FinancialEntry
from app.modules.services.associations import professional_services

__all__ = ["client", "database", "financial_categories", "password_hash"]
entry_root = "/api/v1/financial-entries"
appointment_a, appointment_b = uuid4(), uuid4()


@pytest.fixture(autouse=True)
def financial_appointments(database, financial_categories):
    with Session(database) as session:
        yesterday = datetime.now(UTC) - timedelta(days=1)
        session.add_all(
            Appointment(
                id=identifier,
                business_id=business_id,
                professional_id=professional_id,
                service_id=service_id,
                customer_name="Customer",
                customer_phone="85999999999",
                starts_at=yesterday,
                ends_at=yesterday + timedelta(minutes=30),
                status=AppointmentStatus.CONFIRMED,
                source=AppointmentSource.PANEL,
            )
            for identifier, business_id, professional_id, service_id in (
                (appointment_a, business_a, professional_a, service_a),
                (appointment_b, business_b, professional_b, service_b),
            )
        )
        session.commit()


def entry_payload(**changes):
    return {
        "category_id": str(income_category_a),
        "type": "INCOME",
        "description": "  Service payment  ",
        "amount": "123.45",
        "due_date": "2026-11-15",
        **changes,
    }


def create_entry(client, headers=None, **changes):
    response = client.post(
        entry_root, headers=headers or auth_headers(), json=entry_payload(**changes)
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "entry_type,category_id",
    [("INCOME", income_category_a), ("EXPENSE", expense_category_a)],
)
def test_entry_crud_is_manual_and_preserves_decimal(
    client, database, entry_type, category_id
):
    data = create_entry(
        client,
        type=entry_type,
        category_id=str(category_id),
        appointment_id=str(appointment_a),
        amount="0.10",
    )
    assert UUID(data["id"]).version == 4
    assert data["business_id"] == str(business_a)
    assert data["description"] == "Service payment"
    assert data["amount"] == "0.10"
    assert data["status"] == "PENDING" and data["paid_at"] is None
    assert data["created_at"]
    path = f"{entry_root}/{data['id']}"
    assert client.get(path, headers=auth_headers()).json() == data
    response = client.patch(
        path, headers=auth_headers(), json={"description": "Updated", "amount": "10.25"}
    )
    assert response.status_code == 200
    assert response.json()["appointment_id"] == str(appointment_a)
    assert response.json()["due_date"] == "2026-11-15"
    assert response.json()["amount"] == "10.25"
    with Session(database) as session:
        stored = session.get(FinancialEntry, UUID(data["id"]))
        assert stored.amount == Decimal("10.25")
        assert stored.category.id == category_id
        assert stored.appointment.id == appointment_a
        assert stored.appointment.status == AppointmentStatus.CONFIRMED
    response = client.patch(path, headers=auth_headers(), json={"appointment_id": None})
    assert response.json()["appointment_id"] is None
    response = client.delete(path, headers=auth_headers())
    assert response.status_code == 204 and response.content == b""
    assert client.get(path, headers=auth_headers()).status_code == 404


def test_update_can_change_category_and_type_together(client):
    data = create_entry(client)
    response = client.patch(
        f"{entry_root}/{data['id']}",
        headers=auth_headers(),
        json={"category_id": str(expense_category_a), "type": "EXPENSE"},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "EXPENSE"
    assert response.json()["category_id"] == str(expense_category_a)


def test_period_type_category_status_and_pagination_filters_are_scoped(client):
    first = create_entry(client, due_date="2026-11-01")
    second = create_entry(client, due_date="2026-11-30")
    expense = create_entry(
        client,
        type="EXPENSE",
        category_id=str(expense_category_a),
        due_date="2026-11-20",
    )
    create_entry(client, due_date="2026-12-01")
    foreign = create_entry(
        client, headers=auth_headers(owner_b), category_id=str(income_category_b)
    )
    assert (
        client.post(
            f"{entry_root}/{second['id']}/pay", headers=auth_headers(), json={}
        ).status_code
        == 200
    )
    filters = {
        "start_date": "2026-11-01",
        "end_date": "2026-11-30",
        "business_id": str(business_b),
    }
    response = client.get(entry_root, headers=auth_headers(), params=filters)
    assert [item["id"] for item in response.json()] == [
        second["id"],
        expense["id"],
        first["id"],
    ]
    assert foreign["id"] not in str(response.json())
    response = client.get(
        entry_root,
        headers=auth_headers(),
        params={
            **filters,
            "type": "INCOME",
            "category_id": str(income_category_a),
            "status": "PENDING",
        },
    )
    assert [item["id"] for item in response.json()] == [first["id"]]
    response = client.get(
        entry_root, headers=auth_headers(), params={**filters, "limit": 1, "offset": 1}
    )
    assert [item["id"] for item in response.json()] == [expense["id"]]
    response = client.get(
        entry_root,
        headers=auth_headers(),
        params={"category_id": str(income_category_b)},
    )
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-11-30", "end_date": "2026-11-01"},
        {"start_date": "invalid"},
        {"status": "OTHER"},
        {"type": "OTHER"},
        {"category_id": "invalid"},
        {"offset": -1},
        {"limit": 0},
        {"limit": 101},
    ],
)
def test_invalid_filters_are_rejected(client, params):
    assert (
        client.get(entry_root, headers=auth_headers(), params=params).status_code == 422
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"category_id": str(income_category_b)},
        {"category_id": str(uuid4())},
        {"category_id": str(expense_category_a)},
        {"type": "EXPENSE"},
        {"appointment_id": str(appointment_b)},
        {"appointment_id": str(uuid4())},
    ],
)
@pytest.mark.parametrize("operation", ["create", "update"])
def test_references_must_match_business_and_category_type_without_partial_writes(
    client, database, changes, operation
):
    if operation == "update":
        entry = create_entry(client)
        response = client.patch(
            f"{entry_root}/{entry['id']}",
            headers=auth_headers(),
            json={"description": "Rejected", **changes},
        )
    else:
        response = client.post(
            entry_root,
            headers=auth_headers(),
            json=entry_payload(description="Rejected", **changes),
        )
    assert response.status_code == 422
    with Session(database) as session:
        assert (
            session.scalar(
                select(FinancialEntry).where(FinancialEntry.description == "Rejected")
            )
            is None
        )


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE", "PAY"])
def test_other_business_cannot_read_update_delete_or_pay(client, method):
    foreign = create_entry(
        client, headers=auth_headers(owner_b), category_id=str(income_category_b)
    )
    for entry_id in (foreign["id"], str(uuid4())):
        path = f"{entry_root}/{entry_id}"
        response = (
            client.post(f"{path}/pay", headers=auth_headers(), json={})
            if method == "PAY"
            else client.request(
                method,
                path,
                headers=auth_headers(),
                json={"description": "Rejected"},
                params={"business_id": str(business_b)},
            )
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Financial entry not found"}


@pytest.mark.parametrize(
    "entry_type,category_id",
    [("INCOME", income_category_a), ("EXPENSE", expense_category_a)],
)
def test_payment_records_explicit_date_and_cannot_be_repeated(
    client, database, entry_type, category_id
):
    data = create_entry(
        client,
        type=entry_type,
        category_id=str(category_id),
        appointment_id=str(appointment_a),
    )
    path = f"{entry_root}/{data['id']}"
    response = client.post(
        f"{path}/pay",
        headers=auth_headers(),
        json={"paid_at": "2026-01-01T10:00:00-03:00"},
    )
    assert response.status_code == 200, response.text
    paid = response.json()
    assert paid["status"] == "PAID"
    assert datetime.fromisoformat(paid["paid_at"]).hour == 13
    assert paid["amount"] == data["amount"]
    assert (
        client.post(f"{path}/pay", headers=auth_headers(), json={}).status_code == 409
    )
    assert client.get(path, headers=auth_headers()).json() == paid
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(FinancialEntry)) == 1
        assert (
            session.get(Appointment, appointment_a).status
            == AppointmentStatus.CONFIRMED
        )


def test_default_payment_uses_current_time(client):
    data = create_entry(client)
    before = datetime.now(UTC)
    response = client.post(
        f"{entry_root}/{data['id']}/pay", headers=auth_headers(), json={}
    )
    after = datetime.now(UTC)
    assert response.status_code == 200
    paid_at = datetime.fromisoformat(response.json()["paid_at"]).replace(tzinfo=UTC)
    assert before <= paid_at <= after


@pytest.mark.parametrize(
    "paid_at",
    [
        "2026-01-01T10:00:00",
        "invalid",
        (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    ],
)
def test_payment_rejects_naive_invalid_or_future_dates(client, paid_at):
    data = create_entry(client)
    response = client.post(
        f"{entry_root}/{data['id']}/pay",
        headers=auth_headers(),
        json={"paid_at": paid_at},
    )
    assert response.status_code == 422
    stored = client.get(f"{entry_root}/{data['id']}", headers=auth_headers()).json()
    assert stored["status"] == "PENDING" and stored["paid_at"] is None


@pytest.mark.parametrize(
    "method,payload",
    [
        ("PATCH", {"amount": "999"}),
        ("PATCH", {"status": "CANCELLED"}),
        ("PATCH", {"description": "Changed"}),
        ("DELETE", {}),
    ],
)
def test_paid_entries_cannot_be_edited_cancelled_or_deleted(client, method, payload):
    data = create_entry(client)
    path = f"{entry_root}/{data['id']}"
    paid = client.post(f"{path}/pay", headers=auth_headers(), json={}).json()
    assert (
        client.request(method, path, headers=auth_headers(), json=payload).status_code
        == 409
    )
    assert client.get(path, headers=auth_headers()).json() == paid


def test_cancellation_is_explicit_and_cancelled_entries_cannot_be_paid(client):
    data = create_entry(client)
    path = f"{entry_root}/{data['id']}"
    response = client.patch(path, headers=auth_headers(), json={"status": "CANCELLED"})
    assert response.status_code == 200 and response.json()["paid_at"] is None
    assert (
        client.post(f"{path}/pay", headers=auth_headers(), json={}).status_code == 409
    )
    assert (
        client.get(
            entry_root, headers=auth_headers(), params={"status": "CANCELLED"}
        ).json()[0]["id"]
        == data["id"]
    )
    assert (
        client.patch(
            path, headers=auth_headers(), json={"status": "PENDING"}
        ).status_code
        == 200
    )
    assert (
        client.post(f"{path}/pay", headers=auth_headers(), json={}).status_code == 200
    )


def test_linked_category_cannot_be_deleted_or_change_type_but_can_be_renamed(
    client, database
):
    data = create_entry(client)
    category_path = f"{category_root}/{income_category_a}"
    assert client.delete(category_path, headers=auth_headers()).status_code == 409
    assert (
        client.patch(
            category_path, headers=auth_headers(), json={"type": "EXPENSE"}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            category_path, headers=auth_headers(), json={"name": "Renamed"}
        ).status_code
        == 200
    )
    with Session(database) as session:
        category = session.get(FinancialCategory, income_category_a)
        assert len(category.entries) == 1
        assert category.entries[0].id == UUID(data["id"])
    assert (
        client.delete(f"{entry_root}/{data['id']}", headers=auth_headers()).status_code
        == 204
    )
    assert client.delete(category_path, headers=auth_headers()).status_code == 204


def test_online_booking_does_not_create_income_or_mark_any_entry_paid(client, database):
    tz = ZoneInfo(settings.BUSINESS_TIMEZONE)
    day = datetime.now(UTC).astimezone(tz).date() + timedelta(days=1)
    with Session(database) as session:
        session.add(
            BusinessHour(
                business_id=business_a,
                weekday=day.weekday(),
                opens_at=time(9),
                closes_at=time(18),
            )
        )
        session.execute(
            insert(professional_services),
            [
                {
                    "business_id": business_a,
                    "professional_id": professional_a,
                    "service_id": service_a,
                }
            ],
        )
        session.commit()
    public_root = f"/api/v1/public/businesses/{business_a}"
    slots = client.get(
        f"{public_root}/availability",
        params={
            "service_id": str(service_a),
            "professional_id": str(professional_a),
            "date": day.isoformat(),
        },
    ).json()
    response = client.post(
        f"{public_root}/appointments",
        json={
            "service_id": str(service_a),
            "professional_id": str(professional_a),
            "starts_at": slots[0],
            "customer_name": "New customer",
            "customer_phone": "85988887777",
        },
    )
    assert response.status_code == 201, response.text
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(FinancialEntry)) == 0
    entry = create_entry(client, appointment_id=response.json()["id"])
    assert entry["status"] == "PENDING" and entry["paid_at"] is None
