"""Financial seed validation against disposable databases; never runs against .env."""

from calendar import monthrange
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session
from test_clients import business_a, business_b, database, password_hash
from test_financial_reports import sqlite_timezone

from app.core.config import settings
from app.modules.financial.service import FinancialReportService
from app.modules.financial_categories.models import FinancialCategory
from app.modules.financial_entries.models import FinancialEntry
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.recurring_entries.schemas import RecurringEntryGenerate
from app.modules.recurring_entries.service import RecurringEntryService
from scripts import seed_financial as seed

__all__ = ["database", "password_hash"]
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 11, 12, 20, tzinfo=UTC)


def run_seed(database: Engine, business_id=business_a, **kwargs) -> dict:
    with Session(database) as session:
        return seed.seed_financial(
            session, business_id, app_env="test", tz=TZ, now=kwargs.get("now", NOW)
        )


def entry_count(database: Engine) -> int:
    with Session(database) as session:
        return session.scalar(select(func.count()).select_from(FinancialEntry))


@pytest.fixture
def populated(database: Engine) -> Engine:
    run_seed(database)
    with database.connect() as connection:
        connection.connection.driver_connection.create_function(
            "timezone", 2, sqlite_timezone
        )
    return database


def test_plan_counts_values_dates_and_relationships(populated: Engine) -> None:
    with Session(populated) as session:
        entries = list(session.scalars(select(FinancialEntry)))
        categories = list(session.scalars(select(FinancialCategory)))
        recurrences = list(session.scalars(select(RecurringEntry)))
        assert (len(categories), len(recurrences), len(entries)) == (9, 6, 182)
        assert Counter(entry.status for entry in entries) == {
            seed.PAID: 146,
            seed.PENDING: 22,
            seed.CANCELLED: 14,
        }
        assert Counter(entry.due_date.month for entry in entries) == dict.fromkeys(
            range(5, 12), 26
        )
        assert all(
            item.id.version == 4 for item in [*categories, *recurrences, *entries]
        )
        assert all(
            item.business_id == business_a
            for item in [*categories, *recurrences, *entries]
        )
        assert all(seed.MARKER in item.name for item in categories)
        assert all(seed.MARKER in item.description for item in [*recurrences, *entries])
        categories_by_id = {category.id: category for category in categories}
        recurrence_by_id = {item.id: item for item in recurrences}
        occurrences = set()
        for entry in entries:
            assert entry.amount > 0
            assert seed.START <= entry.due_date <= seed.END
            assert categories_by_id[entry.category_id].type == entry.type
            assert (entry.paid_at is not None) == (entry.status == seed.PAID)
            if entry.paid_at:
                paid = entry.paid_at.replace(tzinfo=UTC)
                assert entry.created_at.replace(tzinfo=UTC) <= paid <= NOW
                assert paid.astimezone(TZ).date().month == entry.due_date.month
            if entry.recurring_entry_id:
                recurrence = recurrence_by_id[entry.recurring_entry_id]
                assert entry.competence == entry.due_date.replace(day=1)
                assert entry.amount == recurrence.amount
                assert entry.category_id == recurrence.category_id
                assert entry.description == recurrence.description
                assert entry.due_date.day == recurrence.due_day
                occurrences.add((recurrence.id, entry.competence))
            else:
                assert entry.competence is None
        assert len(occurrences) == 42


@pytest.mark.parametrize("row", seed.EXPECTED_TOTALS)
def test_expected_monthly_totals_use_existing_report_service(
    populated: Engine, row: tuple
) -> None:
    period, *expected = row
    start = date.fromisoformat(f"{period}-01")
    end = start.replace(day=monthrange(start.year, start.month)[1])
    with Session(populated) as session:
        report = FinancialReportService(session, TZ).summary(
            business_id=business_a, start_date=start, end_date=end
        )
        fields = (
            "paid_income",
            "paid_expenses",
            "balance",
            "pending_income",
            "pending_expenses",
        )
        assert report.model_dump() == dict(
            zip(fields, map(Decimal, expected), strict=True)
        )


def test_cash_flow_profitability_categories_and_overdue_scenarios(
    populated: Engine,
) -> None:
    with Session(populated) as session:
        service = FinancialReportService(session, TZ)
        cash = service.cash_flow(
            business_id=business_a, start_date=seed.START, end_date=seed.END
        )
        assert (cash.total_income, cash.total_expenses, cash.balance) == (
            Decimal(37800),
            Decimal(23560),
            Decimal(14240),
        )
        categories = service.categories(
            business_id=business_a, start_date=seed.START, end_date=seed.END
        )
        assert len(categories.items) == 9
        assert (categories.pending_income, categories.pending_expenses) == (
            Decimal(7850),
            Decimal(2010),
        )
        august = service.profitability(
            business_id=business_a,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        assert august.comparison.paid_income_change_percentage == Decimal("-30.00")
        june = service.profitability(
            business_id=business_a,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
        )
        assert june.comparison.paid_income_change_percentage == Decimal("25.00")
        for month in (9, 11):
            report = service.profitability(
                business_id=business_a,
                start_date=date(2026, month, 1),
                end_date=date(2026, month, monthrange(2026, month)[1]),
            )
            assert report.current_period.financial_result < 0
            assert report.current_period.financial_margin_percentage < 0
        overdue = session.scalar(
            select(func.sum(FinancialEntry.amount)).where(
                FinancialEntry.business_id == business_a,
                FinancialEntry.type == seed.EXPENSE,
                FinancialEntry.status == seed.PENDING,
                FinancialEntry.due_date < seed.REFERENCE_DATE,
            )
        )
        assert overdue == Decimal(1260)
        foreign = service.summary(business_id=business_b)
        assert all(value == 0 for value in foreign.model_dump().values())


def test_idempotent_and_recurrence_generator_does_not_double_count(
    populated: Engine,
) -> None:
    with Session(populated) as session:
        ids_before = set(session.scalars(select(FinancialEntry.id)))
        recurrence_ids = list(session.scalars(select(RecurringEntry.id)))
    result = run_seed(populated)
    assert result["created"] == {"categories": 0, "recurrences": 0, "entries": 0}
    assert result["preserved"] == {"categories": 9, "recurrences": 6, "entries": 182}
    for recurrence_id in recurrence_ids:
        with Session(populated) as session:
            generated = RecurringEntryService(session).generate(
                recurrence_id,
                RecurringEntryGenerate(
                    start_month=seed.START, end_month=date(2026, 11, 1)
                ),
                business_id=business_a,
            )
            assert generated.created_entries == []
            assert len(generated.skipped_competences) == 7
    with Session(populated) as session:
        assert set(session.scalars(select(FinancialEntry.id))) == ids_before
    assert run_seed(populated)["created"]["entries"] == 0


def test_existing_matching_occurrence_with_another_id_is_reused(
    populated: Engine,
) -> None:
    replacement_id = uuid4()
    with Session(populated) as session:
        occurrence = session.scalar(
            select(FinancialEntry).where(FinancialEntry.recurring_entry_id.is_not(None))
        )
        occurrence.id = replacement_id
        session.commit()
    assert run_seed(populated)["created"]["entries"] == 0
    with Session(populated) as session:
        assert session.get(FinancialEntry, replacement_id) is not None
    assert entry_count(populated) == 182


def test_existing_data_and_other_business_are_preserved(database: Engine) -> None:
    original_ids = []
    with Session(database) as session:
        for business_id in (business_a, business_b):
            category = FinancialCategory(
                business_id=business_id, name="Existing category", type=seed.INCOME
            )
            session.add(category)
            session.flush()
            entry = FinancialEntry(
                business_id=business_id,
                category_id=category.id,
                type=seed.INCOME,
                description="Existing entry",
                amount=Decimal("77.77"),
                due_date=seed.START,
                status=seed.PENDING,
            )
            session.add(entry)
            session.flush()
            original_ids.append(entry.id)
        session.commit()
    run_seed(database)
    assert entry_count(database) == 184
    with Session(database) as session:
        for identifier in original_ids:
            record = session.get(FinancialEntry, identifier)
            assert (record.description, record.amount, record.status) == (
                "Existing entry",
                Decimal("77.77"),
                seed.PENDING,
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(FinancialCategory)
                .where(FinancialCategory.business_id == business_b)
            )
            == 1
        )
    run_seed(database, business_b)
    assert entry_count(database) == 366
    with Session(database) as session:
        identifiers = list(session.scalars(select(FinancialEntry.id)))
        assert len(set(identifiers)) == 366


@pytest.mark.parametrize("change", ["amount", "status"])
def test_changed_seed_records_are_never_overwritten(
    populated: Engine, change: str
) -> None:
    with Session(populated) as session:
        entry = session.scalar(
            select(FinancialEntry).where(FinancialEntry.status == seed.PENDING)
        )
        identifier = entry.id
        if change == "amount":
            entry.amount = Decimal("999.99")
        else:
            entry.status = seed.CANCELLED
        session.commit()
    with pytest.raises(seed.SeedError, match="alterado"):
        run_seed(populated)
    with Session(populated) as session:
        entry = session.get(FinancialEntry, identifier)
        assert (
            (entry.amount == Decimal("999.99"))
            if change == "amount"
            else (entry.status == seed.CANCELLED)
        )
    assert entry_count(populated) == 182


def test_failure_rolls_back_new_records(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = seed.ensure_record

    def fail_on_entries(session, model, values, natural_key):
        if model is FinancialEntry:
            raise seed.SeedError("injected failure")
        return original(session, model, values, natural_key)

    monkeypatch.setattr(seed, "ensure_record", fail_on_entries)
    with pytest.raises(seed.SeedError, match="injected"):
        run_seed(database)
    with Session(database) as session:
        for model in (FinancialCategory, RecurringEntry, FinancialEntry):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_missing_business_creates_nothing(database: Engine) -> None:
    with pytest.raises(seed.SeedError, match="encontrada"):
        run_seed(database, uuid4())
    assert entry_count(database) == 0


@pytest.mark.parametrize("environment", ["production", "", "staging"])
def test_non_development_environments_block_before_query(
    database: Engine, environment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(database) as session:
        execute = Mock(side_effect=AssertionError("must not query"))
        monkeypatch.setattr(session, "execute", execute)
        with pytest.raises(seed.SeedError):
            seed.seed_financial(
                session, business_a, app_env=environment, tz=TZ, now=NOW
            )
        execute.assert_not_called()


@pytest.mark.parametrize(
    "name",
    [
        "organizae_production",
        "production",
        "",
        None,
        "organizae_test-production",
    ],
)
def test_unsafe_database_names_are_blocked(name: str | None) -> None:
    with pytest.raises(seed.SeedError):
        seed.guard_environment("development", name)


@pytest.mark.parametrize(
    "name",
    [
        "organizae",
        "organizae_test",
        "organizae_dev",
        "organizae_test_seed",
        "organizae_dev_local",
    ],
)
@pytest.mark.parametrize("environment", ["development", "test"])
def test_allowed_database_names(name: str, environment: str) -> None:
    seed.guard_environment(environment, name)


def test_persistent_sqlite_is_refused_without_connecting() -> None:
    engine = create_engine("sqlite:///organizae_test_seed")
    try:
        with Session(engine) as session, pytest.raises(seed.SeedError):
            seed.guard_session(session, "test")
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "now", [datetime(2026, 11, 11, 20, tzinfo=UTC), datetime(2026, 11, 12, 20)]
)
def test_future_scenario_and_naive_clock_are_refused(
    database: Engine, now: datetime
) -> None:
    with pytest.raises(seed.SeedError, match="relógio"):
        run_seed(database, now=now)
    assert entry_count(database) == 0


def test_existing_transaction_is_not_committed(database: Engine) -> None:
    with Session(database) as session:
        category = FinancialCategory(
            business_id=business_a, name="Uncommitted", type=seed.INCOME
        )
        session.add(category)
        with pytest.raises(seed.SeedError, match="sessão nova"):
            seed.seed_financial(session, business_a, app_env="test", tz=TZ, now=NOW)
        assert category in session.new
        session.rollback()
    assert entry_count(database) == 0


def test_preview_never_opens_database(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import app.db.session as db

    factory = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(db, "SessionLocal", factory)
    assert seed.main(["--preview"]) == 0
    assert '"entries": 182' in capsys.readouterr().out
    factory.assert_not_called()


def test_cli_production_guard_and_missing_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.db.session as db

    factory = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DB_NAME", "organizae")
    with pytest.raises(SystemExit) as error:
        seed.main(["--business-id", str(business_a)])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        seed.main([])
    assert error.value.code == 2
    factory.assert_not_called()
