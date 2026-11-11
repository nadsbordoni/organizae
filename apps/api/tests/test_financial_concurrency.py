import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest
from sqlalchemy import text, update
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
    # Register every ORM target before building the disposable PostgreSQL schema.
    import app.db.session  # noqa: F401

from app.modules.businesses.models import Business, ServiceMode
from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_entries.exceptions import FinancialEntryConflictError
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.schemas import (
    FinancialEntryPayment,
    FinancialEntryUpdate,
)
from app.modules.financial_entries.service import FinancialEntryService

__all__ = ["postgres_agenda"]


@pytest.fixture
def financial_agenda(postgres_agenda):
    engine, business_id, *_ = postgres_agenda
    with Session(engine) as session:
        category = FinancialCategory(
            business_id=business_id, name="Income", type=FinancialType.INCOME
        )
        session.add(category)
        session.flush()
        entry = FinancialEntry(
            business_id=business_id,
            category_id=category.id,
            type=FinancialType.INCOME,
            description="Payment",
            amount=Decimal("10.25"),
            due_date=date(2026, 11, 10),
        )
        session.add(entry)
        session.commit()
        yield engine, business_id, entry.id


@pytest.mark.parametrize("second_operation", ["pay", "update", "delete"])
def test_postgresql_payment_locks_prevent_duplicate_payment_and_mutating_paid_entries(
    financial_agenda, second_operation
):
    engine, business_id, entry_id = financial_agenda
    first_locked, release_first, second_attempting = Event(), Event(), Event()
    second_pid = []

    def operate(first):
        with Session(engine) as session:
            service = FinancialEntryService(session)
            original = service.repository.get_by_id
            if not first:
                stale = original(entry_id, business_id=business_id)
                assert stale.status == FinancialEntryStatus.PENDING

            def controlled_get(identifier, *, business_id, lock=False):
                if lock and not first:
                    second_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                    second_attempting.set()
                result = original(identifier, business_id=business_id, lock=lock)
                if first and lock:
                    first_locked.set()
                    assert release_first.wait(5)
                return result

            service.repository.get_by_id = controlled_get
            try:
                if first or second_operation == "pay":
                    service.pay(
                        entry_id,
                        FinancialEntryPayment(paid_at=datetime(2026, 1, 1, tzinfo=UTC)),
                        business_id=business_id,
                    )
                elif second_operation == "update":
                    service.update(
                        entry_id,
                        FinancialEntryUpdate(amount="999"),
                        business_id=business_id,
                    )
                else:
                    service.delete(entry_id, business_id=business_id)
                return "paid"
            except FinancialEntryConflictError:
                assert not session.in_transaction()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(operate, True)
        try:
            assert first_locked.wait(5)
            loser = executor.submit(operate, False)
            assert second_attempting.wait(5)
            with engine.connect() as connection:
                deadline = monotonic() + 3
                waiting = 0
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
                    "Concurrent mutation did not wait on the PostgreSQL row lock"
                )
        finally:
            release_first.set()
        assert winner.result(timeout=10) == "paid"
        assert loser.result(timeout=10) == "conflict"
    with Session(engine) as session:
        stored = session.get(FinancialEntry, entry_id)
        assert stored.status == FinancialEntryStatus.PAID
        assert stored.amount == Decimal("10.25")


def test_postgresql_enforces_tenant_type_payment_and_nan_constraints(financial_agenda):
    engine, business_id, entry_id = financial_agenda
    with Session(engine) as session:
        other_business = Business(
            name="Other",
            category_id=1,
            whatsapp="85999999999",
            service_mode=ServiceMode.PRESENCIAL,
        )
        session.add(other_business)
        session.flush()
        foreign_category = FinancialCategory(
            business_id=other_business.id, name="Foreign", type=FinancialType.INCOME
        )
        session.add(foreign_category)
        session.commit()
        foreign_id = foreign_category.id
        for changes in (
            {"category_id": foreign_id},
            {"type": FinancialType.EXPENSE},
            {"status": FinancialEntryStatus.PAID},
            {"amount": Decimal(-1)},
            {"amount": Decimal("NaN")},
        ):
            with pytest.raises(IntegrityError):
                session.execute(
                    update(FinancialEntry)
                    .where(FinancialEntry.id == entry_id)
                    .values(**changes)
                )
            session.rollback()
        assert session.get(FinancialEntry, entry_id).business_id == business_id
