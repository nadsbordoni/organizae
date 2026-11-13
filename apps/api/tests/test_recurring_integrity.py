from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_clients import (
    auth_headers,
    business_a,
    business_b,
    client,
    database,
    password_hash,
)
from test_financial_categories import (
    financial_categories,
    income_category_a,
    income_category_b,
)
from test_recurring_entries import create_recurrence, generate, payload, root

from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.financial_categories.models import FinancialCategory
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.repository import FinancialEntryRepository
from app.modules.financial_entries.schemas import FinancialEntryCreate
from app.modules.recurring_entries.exceptions import InvalidRecurringEntryError
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.recurring_entries.repository import RecurringEntryRepository
from app.modules.recurring_entries.schemas import (
    RecurringEntryCreate,
    RecurringEntryUpdate,
)
from app.modules.recurring_entries.service import RecurringEntryService

__all__ = ["client", "database", "financial_categories", "password_hash"]


def state(engine):
    with Session(engine) as session:
        return (
            set(
                session.execute(
                    select(
                        RecurringEntry.id,
                        RecurringEntry.category_id,
                        RecurringEntry.type,
                        RecurringEntry.description,
                        RecurringEntry.amount,
                        RecurringEntry.due_day,
                        RecurringEntry.start_date,
                        RecurringEntry.end_date,
                        RecurringEntry.is_active,
                    )
                )
            ),
            set(
                session.execute(
                    select(
                        FinancialEntry.id,
                        FinancialEntry.recurring_entry_id,
                        FinancialEntry.competence,
                        FinancialEntry.amount,
                        FinancialEntry.status,
                    )
                )
            ),
        )


@pytest.mark.parametrize("operation", ["create", "update", "delete", "generate"])
@pytest.mark.parametrize(
    "failure,status",
    [
        (IntegrityError("private query", {}, Exception("private")), 409),
        (RuntimeError("private"), 500),
    ],
)
def test_every_mutation_rolls_back_on_commit_failure(
    client, database, operation, failure, status
):
    existing = create_recurrence(client)
    before = state(database)
    original_rollback = Session.rollback
    with (
        patch.object(Session, "commit", side_effect=failure),
        patch.object(
            Session, "rollback", autospec=True, side_effect=original_rollback
        ) as rollback,
    ):
        if operation == "create":
            response = client.post(root, headers=auth_headers(), json=payload())
        elif operation == "update":
            response = client.patch(
                f"{root}/{existing['id']}",
                headers=auth_headers(),
                json={"amount": "999"},
            )
        elif operation == "delete":
            response = client.delete(f"{root}/{existing['id']}", headers=auth_headers())
        else:
            response = generate(client, existing["id"])
    assert response.status_code == status
    assert "private" not in response.text
    rollback.assert_called_once()
    assert state(database) == before


def test_failure_in_second_month_rolls_back_entire_batch(client, database):
    entry = create_recurrence(client)
    original_create = FinancialEntryRepository.create
    calls = []

    def fail_second(repository, data, **kwargs):
        calls.append(data.due_date)
        if len(calls) == 2:
            raise RuntimeError("private")
        return original_create(repository, data, **kwargs)

    with patch.object(FinancialEntryRepository, "create", new=fail_second):
        assert generate(client, entry["id"]).status_code == 500
    assert len(calls) == 2
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(FinancialEntry)) == 0
    assert len(generate(client, entry["id"]).json()["created_entries"]) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"category_id": income_category_b},
        {"category_id": uuid4()},
        {"business_id": business_b},
        {"type": "EXPENSE"},
        {"type": "OTHER"},
        {"due_day": 0},
        {"due_day": 32},
        {"amount": Decimal(-1)},
        {"amount": Decimal(10000000000)},
        {"end_date": date(2025, 1, 1)},
        {"description": " "},
    ],
)
def test_database_rejects_invalid_recurrence_fields(client, database, changes):
    entry = create_recurrence(client)
    with Session(database) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                update(RecurringEntry)
                .where(RecurringEntry.id == UUID(entry["id"]))
                .values(**changes)
            )
        session.rollback()
        assert session.get(RecurringEntry, UUID(entry["id"])).amount == Decimal(
            "100.10"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"recurring_entry_id": None},
        {"competence": None},
        {"competence": date(2026, 1, 15)},
        {"business_id": business_b, "category_id": income_category_b},
        {"recurring_entry_id": uuid4()},
    ],
)
def test_database_rejects_missing_pairs_invalid_month_and_foreign_recurrence(
    client, database, changes
):
    recurrence = create_recurrence(client)
    entry = generate(client, recurrence["id"]).json()["created_entries"][0]
    with Session(database) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                update(FinancialEntry)
                .where(FinancialEntry.id == UUID(entry["id"]))
                .values(**changes)
            )
        session.rollback()
        assert session.get(FinancialEntry, UUID(entry["id"])).competence == date(
            2026, 1, 1
        )


@pytest.mark.parametrize("status", list(FinancialEntryStatus))
def test_database_unique_competence_covers_all_statuses(client, database, status):
    recurrence = create_recurrence(client)
    entry = generate(client, recurrence["id"]).json()["created_entries"][0]
    with Session(database) as session:
        duplicate = FinancialEntry(
            business_id=business_a,
            category_id=income_category_a,
            type="INCOME",
            description="Duplicate",
            amount="1",
            due_date=date(2026, 1, 31),
            recurring_entry_id=UUID(recurrence["id"]),
            competence=date(2026, 1, 1),
            status=status,
            paid_at=datetime(2026, 1, 1, tzinfo=UTC)
            if status == FinancialEntryStatus.PAID
            else None,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(FinancialEntry, UUID(entry["id"])).amount == Decimal(
            "100.10"
        )


def test_referenced_category_and_loaded_recurrence_cannot_be_physically_deleted(
    client, database
):
    recurrence = create_recurrence(client)
    generate(client, recurrence["id"])
    with Session(database) as session:
        parent = session.get(RecurringEntry, UUID(recurrence["id"]))
        assert len(parent.entries) == 3
        session.delete(parent)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(FinancialEntry)) == 3
        with pytest.raises(IntegrityError):
            session.execute(
                delete(FinancialCategory).where(
                    FinancialCategory.id == income_category_a
                )
            )
        session.rollback()


def test_repositories_leave_transaction_control_to_service_and_partial_update_preserves_fields(
    database,
):
    with Session(database) as session:
        repository = RecurringEntryRepository(session)
        with (
            patch.object(
                session, "commit", side_effect=AssertionError("Repository committed")
            ),
            patch.object(
                session,
                "rollback",
                side_effect=AssertionError("Repository rolled back"),
            ),
        ):
            entry = repository.create(
                RecurringEntryCreate(**payload()), business_id=business_a
            )
            identifier = entry.id
            repository.update(entry, RecurringEntryUpdate(description="Changed"))
            assert entry.amount == Decimal("100.10") and entry.due_day == 31
            assert repository.get_by_id(identifier, business_id=business_b) is None
            assert (
                repository.generated_competences(
                    identifier,
                    business_id=business_b,
                    start_month=date(2026, 1, 1),
                    end_month=date(2026, 2, 1),
                )
                == set()
            )
        session.rollback()
        assert repository.get_by_id(identifier, business_id=business_a) is None


def test_scope_and_row_lock_refresh_stale_recurring_identity_map():
    session = Mock(spec=Session)
    identifier = uuid4()
    RecurringEntryRepository(session).get_by_id(
        identifier, business_id=business_a, lock=True
    )
    statement = session.scalar.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(compiled)
    assert (
        identifier in compiled.params.values()
        and business_a in compiled.params.values()
    )
    assert statement.get_execution_options()["populate_existing"] is True


def test_missing_business_on_create_is_rejected_and_rolled_back(database):
    with Session(database) as session:
        with pytest.raises(BusinessNotFoundError):
            RecurringEntryService(session).create(
                RecurringEntryCreate(**payload()), business_id=uuid4()
            )
        assert not session.in_transaction()


@pytest.mark.parametrize("offset,limit", [(-1, 100), (0, 0), (0, 101)])
def test_service_rejects_invalid_pagination(database, offset, limit):
    with Session(database) as session, pytest.raises(InvalidRecurringEntryError):
        RecurringEntryService(session).list(
            business_id=business_a, offset=offset, limit=limit
        )


def test_manual_and_recurring_entries_share_repository_without_forcing_recurrence(
    database,
):
    with Session(database) as session:
        entry = FinancialEntryRepository(session).create(
            FinancialEntryCreate(
                category_id=income_category_a,
                type="INCOME",
                description="Manual",
                amount="1",
                due_date=date(2026, 1, 1),
            ),
            business_id=business_a,
        )
        assert entry.recurring_entry_id is None and entry.competence is None
        session.rollback()
