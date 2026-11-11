import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_appointment_concurrency import postgres_agenda

with patch.dict(
    os.environ,
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    import app.db.session  # noqa: F401

from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_entries.models import FinancialEntry
from app.modules.recurring_entries.exceptions import RecurringEntryConflictError
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.recurring_entries.schemas import (
    RecurringEntryGenerate,
    RecurringEntryUpdate,
)
from app.modules.recurring_entries.service import RecurringEntryService

__all__ = ["postgres_agenda"]


@pytest.fixture
def recurring_agenda(postgres_agenda):
    engine, business_id, *_ = postgres_agenda
    with Session(engine) as session:
        category = FinancialCategory(
            business_id=business_id, name="Rent", type=FinancialType.EXPENSE
        )
        session.add(category)
        session.flush()
        recurrence = RecurringEntry(
            business_id=business_id,
            category_id=category.id,
            type=FinancialType.EXPENSE,
            description="Rent",
            amount=Decimal("100.10"),
            due_day=31,
            start_date=date(2026, 1, 1),
        )
        session.add(recurrence)
        session.commit()
        identifier = recurrence.id
    yield engine, business_id, identifier


@pytest.mark.parametrize("first_operation", ["generate", "update", "deactivate"])
def test_postgresql_serializes_generation_with_generation_edit_and_suspension(
    recurring_agenda, first_operation
):
    engine, business_id, identifier = recurring_agenda
    first_locked, release_first, second_attempting = Event(), Event(), Event()
    second_pid = []
    period = RecurringEntryGenerate(
        start_month=date(2026, 1, 1), end_month=date(2026, 3, 1)
    )

    def operate(first):
        with Session(engine) as session:
            service = RecurringEntryService(session)
            original = service.repository.get_by_id
            if not first:
                stale = original(identifier, business_id=business_id)
                assert stale.is_active is True and stale.amount == Decimal("100.10")

            def controlled_get(entry_id, *, business_id, lock=False):
                if lock and not first:
                    second_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                    second_attempting.set()
                result = original(entry_id, business_id=business_id, lock=lock)
                if lock and first:
                    first_locked.set()
                    assert release_first.wait(5)
                return result

            service.repository.get_by_id = controlled_get
            try:
                if first and first_operation == "update":
                    service.update(
                        identifier,
                        RecurringEntryUpdate(amount="200", due_day=10),
                        business_id=business_id,
                    )
                    return "updated"
                if first and first_operation == "deactivate":
                    service.delete(identifier, business_id=business_id)
                    return "deactivated"
                result = service.generate(identifier, period, business_id=business_id)
                return len(result.created_entries), len(result.skipped_competences)
            except RecurringEntryConflictError:
                assert not session.in_transaction()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(operate, True)
        try:
            assert first_locked.wait(5)
            second_future = executor.submit(operate, False)
            assert second_attempting.wait(5)
            with engine.connect() as connection:
                waiting = 0
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    waiting = connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE pid = :pid AND wait_event_type = 'Lock'"
                        ),
                        {"pid": second_pid[0]},
                    )
                    connection.rollback()
                    if waiting:
                        break
                    sleep(0.01)
                assert waiting == 1, (
                    "Concurrent generation did not wait on the recurrence row lock"
                )
        finally:
            release_first.set()
        first_result = first_future.result(timeout=10)
        second_result = second_future.result(timeout=10)
    with Session(engine) as session:
        entries = list(
            session.scalars(
                select(FinancialEntry)
                .where(
                    FinancialEntry.recurring_entry_id == identifier,
                )
                .order_by(FinancialEntry.competence)
            ).all()
        )
        if first_operation == "generate":
            assert first_result == (3, 0) and second_result == (0, 3)
            assert len(entries) == 3
        elif first_operation == "update":
            assert first_result == "updated" and second_result == (3, 0)
            assert all(
                entry.amount == Decimal("200.00") and entry.due_date.day == 10
                for entry in entries
            )
        else:
            assert first_result == "deactivated" and second_result == "conflict"
            assert entries == []
            assert session.get(RecurringEntry, identifier).is_active is False


def test_postgresql_recurrence_constraints_reject_duplicate_competences_and_partial_metadata(
    recurring_agenda,
):
    engine, business_id, identifier = recurring_agenda
    with Session(engine) as session:
        result = RecurringEntryService(session).generate(
            identifier,
            RecurringEntryGenerate(
                start_month=date(2026, 1, 1), end_month=date(2026, 2, 1)
            ),
            business_id=business_id,
        )
        first, second = result.created_entries
        for changes, constraint in (
            (
                {"competence": first.competence},
                "uq_financial_entries_recurrence_competence",
            ),
            ({"competence": None}, "ck_financial_entries_recurrence_pair"),
            ({"recurring_entry_id": None}, "ck_financial_entries_recurrence_pair"),
            ({"competence": date(2026, 2, 2)}, "ck_financial_entries_competence_month"),
        ):
            with pytest.raises(IntegrityError) as error:
                session.execute(
                    update(FinancialEntry)
                    .where(FinancialEntry.id == second.id)
                    .values(**changes)
                )
            assert error.value.orig.diag.constraint_name == constraint
            session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(
                update(RecurringEntry)
                .where(RecurringEntry.id == identifier)
                .values(amount=Decimal("NaN"))
            )
        session.rollback()
