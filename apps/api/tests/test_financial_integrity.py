from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_clients import (
    auth_headers,
    business_a,
    business_b,
    client,
    database,
    inactive_user,
    password_hash,
    unassigned_user,
)
from test_financial_categories import (
    category_root,
    financial_categories,
    income_category_a,
    income_category_b,
)
from test_financial_entries import (
    appointment_a,
    appointment_b,
    create_entry,
    entry_payload,
    entry_root,
    financial_appointments,
)

from app.modules.appointments.models import Appointment
from app.modules.financial_categories.models import FinancialCategory
from app.modules.financial_categories.repository import FinancialCategoryRepository
from app.modules.financial_entries.models import FinancialEntry
from app.modules.financial_entries.repository import FinancialEntryRepository
from app.modules.financial_entries.schemas import (
    FinancialEntryCreate,
    FinancialEntryUpdate,
)

__all__ = [
    "client",
    "database",
    "financial_appointments",
    "financial_categories",
    "password_hash",
]


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", entry_root),
        ("GET", entry_root),
        ("GET", f"{entry_root}/{uuid4()}"),
        ("PATCH", f"{entry_root}/{uuid4()}"),
        ("DELETE", f"{entry_root}/{uuid4()}"),
        ("POST", f"{entry_root}/{uuid4()}/pay"),
    ],
)
@pytest.mark.parametrize(
    "identity,status",
    [(None, 401), ("invalid", 401), (inactive_user, 401), (unassigned_user, 403)],
)
def test_all_entry_routes_require_active_jwt_and_business(
    client, method, path, identity, status
):
    headers = (
        {}
        if identity is None
        else {"Authorization": "Bearer invalid"}
        if identity == "invalid"
        else auth_headers(identity)
    )
    response = client.request(method, path, headers=headers, json=entry_payload())
    assert response.status_code == status
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "field,value",
    [
        ("category_id", None),
        ("category_id", "invalid"),
        ("category_id", 1),
        ("category_id", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
        ("type", None),
        ("type", "OTHER"),
        ("description", None),
        ("description", "  "),
        ("description", "a" * 501),
        ("amount", None),
        ("amount", "0"),
        ("amount", "-1"),
        ("amount", "1.001"),
        ("amount", "10000000000.00"),
        ("amount", "NaN"),
        ("amount", "Infinity"),
        ("due_date", None),
        ("due_date", "2026-13-40"),
        ("business_id", str(business_b)),
        ("id", str(uuid4())),
        ("created_at", "2026-01-01T10:00:00Z"),
        ("paid_at", "2026-01-01T10:00:00Z"),
        ("status", "PAID"),
    ],
)
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_entry_validation_prevents_invalid_money_fields_and_identity_injection(
    client, field, value, method
):
    if method == "POST":
        response = client.post(
            entry_root, headers=auth_headers(), json=entry_payload(**{field: value})
        )
    else:
        data = create_entry(client)
        response = client.patch(
            f"{entry_root}/{data['id']}", headers=auth_headers(), json={field: value}
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"category_id": income_category_b},
        {"type": "EXPENSE"},
        {"appointment_id": appointment_b},
        {"business_id": business_b},
        {"status": "PAID"},
        {"paid_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"status": "CANCELLED", "paid_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"amount": 0},
        {"amount": -1},
        {"amount": 10000000000},
    ],
)
def test_database_rejects_invalid_financial_references_and_payment_states(
    client, database, changes
):
    data = create_entry(client, appointment_id=str(appointment_a))
    with Session(database) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                update(FinancialEntry)
                .where(FinancialEntry.id == UUID(data["id"]))
                .values(**changes)
            )
        session.rollback()
        entry = session.get(FinancialEntry, UUID(data["id"]))
        assert entry.business_id == business_a
        assert entry.category_id == income_category_a
        assert entry.status.value == "PENDING" and entry.paid_at is None


def test_database_preserves_references_when_deleting_category_or_appointment(
    client, database
):
    create_entry(client, appointment_id=str(appointment_a))
    with Session(database) as session:
        category = session.get(FinancialCategory, income_category_a)
        assert len(category.entries) == 1
        session.delete(category)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(delete(Appointment).where(Appointment.id == appointment_a))
        session.rollback()
        assert session.get(Appointment, appointment_a) is not None


def test_reference_constraint_handles_category_delete_race(client):
    create_entry(client)
    with patch.object(FinancialCategoryRepository, "has_entries", return_value=False):
        response = client.delete(
            f"{category_root}/{income_category_a}", headers=auth_headers()
        )
    assert response.status_code == 409


def database_state(database):
    with Session(database) as session:
        categories = set(
            session.execute(
                select(
                    FinancialCategory.id,
                    FinancialCategory.business_id,
                    FinancialCategory.name,
                    FinancialCategory.type,
                )
            )
        )
        entries = set(
            session.execute(
                select(
                    FinancialEntry.id,
                    FinancialEntry.business_id,
                    FinancialEntry.category_id,
                    FinancialEntry.type,
                    FinancialEntry.description,
                    FinancialEntry.amount,
                    FinancialEntry.due_date,
                    FinancialEntry.status,
                    FinancialEntry.paid_at,
                )
            )
        )
    return categories, entries


@pytest.mark.parametrize(
    "operation",
    [
        "category_create",
        "category_update",
        "category_delete",
        "entry_create",
        "entry_update",
        "entry_delete",
        "entry_pay",
    ],
)
@pytest.mark.parametrize(
    "failure,status",
    [
        (IntegrityError("private query", {}, Exception("private")), 409),
        (RuntimeError("private"), 500),
    ],
)
def test_all_mutations_roll_back_and_hide_internal_errors(
    client, database, operation, failure, status
):
    if operation in ("entry_update", "entry_delete", "entry_pay"):
        entry = create_entry(client)
        path = f"{entry_root}/{entry['id']}"
    before = database_state(database)
    original_rollback = Session.rollback
    with (
        patch.object(Session, "commit", side_effect=failure),
        patch.object(
            Session, "rollback", autospec=True, side_effect=original_rollback
        ) as rollback,
    ):
        if operation == "category_create":
            response = client.post(
                category_root,
                headers=auth_headers(),
                json={"name": "Transient", "type": "INCOME"},
            )
        elif operation == "category_update":
            response = client.patch(
                f"{category_root}/{income_category_a}",
                headers=auth_headers(),
                json={"name": "Transient"},
            )
        elif operation == "category_delete":
            response = client.delete(
                f"{category_root}/{income_category_a}", headers=auth_headers()
            )
        elif operation == "entry_create":
            response = client.post(
                entry_root, headers=auth_headers(), json=entry_payload()
            )
        elif operation == "entry_update":
            response = client.patch(
                path, headers=auth_headers(), json={"amount": "999"}
            )
        elif operation == "entry_delete":
            response = client.delete(path, headers=auth_headers())
        else:
            response = client.post(f"{path}/pay", headers=auth_headers(), json={})
    assert response.status_code == status
    assert "private" not in response.text
    rollback.assert_called_once()
    assert database_state(database) == before


def test_repository_does_not_commit_or_rollback_and_partial_updates_preserve_omissions(
    database,
):
    with Session(database) as session:
        repository = FinancialEntryRepository(session)
        with patch.object(
            session, "commit", side_effect=AssertionError("Repository committed")
        ):
            entry = repository.create(
                FinancialEntryCreate(**entry_payload()), business_id=business_a
            )
            identifier = entry.id
            repository.update(entry, FinancialEntryUpdate(description="Changed"))
            repository.record_payment(entry, datetime(2026, 1, 1, tzinfo=UTC))
            assert repository.get_by_id(identifier, business_id=business_b) is None
            assert entry.amount == Decimal("123.45")
        session.rollback()
        assert repository.get_by_id(identifier, business_id=business_a) is None


def test_mutation_query_locks_row_and_refreshes_identity_map():
    session = Mock(spec=Session)
    entry_id = uuid4()
    FinancialEntryRepository(session).get_by_id(
        entry_id, business_id=business_a, lock=True
    )
    statement = session.scalar.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(compiled)
    assert "financial_entries.business_id =" in str(compiled)
    assert business_a in compiled.params.values()
    assert entry_id in compiled.params.values()
    assert statement.get_execution_options()["populate_existing"] is True
