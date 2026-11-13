from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import OperationalError
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
    expense_category_a,
    financial_categories,
    income_category_a,
    income_category_b,
)
from test_financial_reports import sqlite_timezone

from app.core.config import settings
from app.main import app
from app.modules.assistant.exceptions import AssistantUnavailableError
from app.modules.financial.exceptions import InvalidFinancialReportError
from app.modules.financial.service import FinancialReportService
from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.schemas import FinancialEntryPayment
from app.modules.financial_entries.service import FinancialEntryService
from app.modules.financial_insights.explanations import explanation_cache
from app.modules.financial_insights.route import (
    get_insight_clock,
    get_insights_provider,
    get_insights_service,
)
from app.modules.financial_insights.schemas import InsightType
from app.modules.financial_insights.service import (
    FinancialInsightsService,
    resolve_periods,
)

__all__ = ["client", "database", "financial_categories", "password_hash"]
NOW = datetime(2026, 11, 13, 15, tzinfo=UTC)
TZ = ZoneInfo("America/Fortaleza")
ROOT = "/api/v1/financial/insights"
foreign_expense = uuid4()


@pytest.fixture(autouse=True)
def setup_insights(database: Engine, financial_categories, monkeypatch):
    monkeypatch.setattr(settings, "BUSINESS_TIMEZONE", TZ.key)
    with database.connect() as connection:
        connection.connection.driver_connection.create_function(
            "timezone", 2, sqlite_timezone
        )
    with Session(database) as session:
        session.add(
            FinancialCategory(
                id=foreign_expense,
                business_id=business_b,
                name="Foreign expense",
                type="EXPENSE",
            )
        )
        session.commit()
    explanation_cache.clear()
    app.dependency_overrides[get_insight_clock] = lambda: NOW
    app.dependency_overrides[get_insights_provider] = lambda: None
    yield
    for dependency in (get_insight_clock, get_insights_provider, get_insights_service):
        app.dependency_overrides.pop(dependency, None)
    explanation_cache.clear()


def entry(
    amount: str,
    day: str = "2026-11-05",
    kind: FinancialType = FinancialType.INCOME,
    status: FinancialEntryStatus = FinancialEntryStatus.PAID,
    business_id: UUID = business_a,
    due_date: str | None = None,
    paid_at: datetime | None = None,
) -> FinancialEntry:
    category_id = (
        (income_category_a if business_id == business_a else income_category_b)
        if kind == FinancialType.INCOME
        else (expense_category_a if business_id == business_a else foreign_expense)
    )
    return FinancialEntry(
        business_id=business_id,
        category_id=category_id,
        type=kind,
        description="Fictitious test",
        amount=Decimal(amount),
        due_date=date.fromisoformat(due_date or day),
        status=status,
        paid_at=(paid_at or datetime.fromisoformat(day + "T15:00:00+00:00"))
        if status == FinancialEntryStatus.PAID
        else None,
    )


def add(database: Engine, *entries: FinancialEntry) -> None:
    with Session(database) as session:
        session.add_all(entries)
        session.commit()


def analyze(database: Engine, **kwargs):
    with Session(database) as session:
        return FinancialInsightsService(session, TZ).analyze(
            business_id=business_a, now=NOW, **kwargs
        )


def kinds(response) -> set:
    return {item.type for item in response.insights}


def fetch(client, **params) -> dict:
    response = client.get(ROOT, headers=auth_headers(), params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("80.00", False),
        ("79.99", True),
        ("80.01", False),
        ("100.00", False),
    ],
)
def test_revenue_drop_uses_strict_threshold(database, amount, expected):
    add(database, entry("100", "2026-10-05"), entry(amount))
    response = analyze(database)
    assert (InsightType.REVENUE_DROP in kinds(response)) is expected
    if expected:
        insight = response.insights[0]
        assert insight.variation_percentage == Decimal("-20.01")
        assert insight.values.paid_income == Decimal(amount)
        assert insight.values.previous_paid_income == Decimal(100)


def test_threshold_does_not_use_rounded_percentage(database):
    add(database, entry("10000", "2026-10-05"), entry("7999.99"))
    response = analyze(database)
    assert kinds(response) == {InsightType.REVENUE_DROP}
    assert response.insights[0].variation_percentage == Decimal("-20.00")


@pytest.mark.parametrize(
    ("amount", "expected"), [("120.00", False), ("120.01", True), ("119.99", False)]
)
def test_expense_increase(database, amount, expected):
    add(
        database,
        entry("1000", "2026-10-05"),
        entry("1000"),
        entry("100", "2026-10-05", FinancialType.EXPENSE),
        entry(amount, kind=FinancialType.EXPENSE),
    )
    response = analyze(database)
    assert (InsightType.EXPENSE_INCREASE in kinds(response)) is expected
    if expected:
        assert response.insights[0].variation_percentage == Decimal("20.01")


@pytest.mark.parametrize(
    ("income", "expenses", "expected"),
    [
        ("100", "101", True),
        ("100", "100", False),
        ("100", "99", False),
        ("0", "10", True),
    ],
)
def test_negative_result(database, income, expenses, expected):
    records = [entry(expenses, kind=FinancialType.EXPENSE)]
    if Decimal(income):
        records.append(entry(income))
    add(database, *records)
    response = analyze(database)
    assert (InsightType.NEGATIVE_RESULT in kinds(response)) is expected
    if expected:
        assert response.insights[0].severity.value == "CRITICAL"
        assert response.insights[0].values.financial_result == Decimal(
            income
        ) - Decimal(expenses)


@pytest.mark.parametrize(
    ("status", "day", "kind", "expected"),
    [
        ("PENDING", "2026-11-12", "EXPENSE", True),
        ("PENDING", "2026-11-13", "EXPENSE", False),
        ("PENDING", "2026-11-14", "EXPENSE", False),
        ("PAID", "2026-11-12", "EXPENSE", False),
        ("CANCELLED", "2026-11-12", "EXPENSE", False),
        ("PENDING", "2026-11-12", "INCOME", False),
    ],
)
def test_overdue_status_type_and_strict_due_date(database, status, day, kind, expected):
    add(database, entry("30", day, FinancialType(kind), FinancialEntryStatus(status)))
    response = analyze(database)
    assert (InsightType.OVERDUE_EXPENSES in kinds(response)) is expected


def test_overdue_aggregates_all_dates_and_is_not_duplicated(database):
    add(
        database,
        entry("10", "2026-09-01", FinancialType.EXPENSE, FinancialEntryStatus.PENDING),
        entry("20", "2026-11-12", FinancialType.EXPENSE, FinancialEntryStatus.PENDING),
        entry(
            "1000", "2026-11-13", FinancialType.EXPENSE, FinancialEntryStatus.PENDING
        ),
    )
    response = analyze(database, month=date(2026, 10, 1))
    assert len(response.insights) == 1
    insight = response.insights[0]
    assert insight.type == InsightType.OVERDUE_EXPENSES
    assert insight.values.overdue_amount == Decimal(30)
    assert insight.values.overdue_count == 2
    assert insight.period.start_date == date(2026, 9, 1)
    assert insight.period.end_date == date(2026, 11, 12)
    assert insight.comparison_period is None


@pytest.mark.parametrize(
    "scenario",
    ["empty", "previous_only", "current_only", "pending_only", "expenses_only"],
)
def test_no_false_revenue_drop_for_missing_receipts_or_zero_base(database, scenario):
    if scenario in ("previous_only", "pending_only", "expenses_only"):
        add(database, entry("100", "2026-10-05"))
    if scenario == "current_only":
        add(database, entry("20"))
    if scenario == "pending_only":
        add(database, entry("20", status=FinancialEntryStatus.PENDING))
    if scenario == "expenses_only":
        add(database, entry("20", kind=FinancialType.EXPENSE))
    response = analyze(database)
    assert InsightType.REVENUE_DROP not in kinds(response)
    assert InsightType.EXPENSE_INCREASE not in kinds(response)
    if scenario == "empty":
        assert response.insights == []


@pytest.mark.parametrize(
    ("month", "today", "end", "previous_start", "previous_end", "partial"),
    [
        (None, "2026-11-13", "2026-11-13", "2026-10-01", "2026-10-13", True),
        ("2026-10-01", "2026-11-13", "2026-10-31", "2026-09-01", "2026-09-30", False),
        (None, "2026-03-30", "2026-03-30", "2026-02-01", "2026-02-28", True),
        (None, "2024-03-30", "2024-03-30", "2024-02-01", "2024-02-29", True),
        ("2026-02-01", "2026-03-13", "2026-02-28", "2026-01-01", "2026-01-31", False),
        (None, "2026-01-13", "2026-01-13", "2025-12-01", "2025-12-13", True),
        (None, "2026-02-28", "2026-02-28", "2026-01-01", "2026-01-31", False),
    ],
)
def test_calendar_period_resolution(
    month, today, end, previous_start, previous_end, partial
):
    period, previous, is_partial = resolve_periods(
        date.fromisoformat(month) if month else None, date.fromisoformat(today)
    )
    assert period.end_date.isoformat() == end
    assert previous.start_date.isoformat() == previous_start
    assert previous.end_date.isoformat() == previous_end
    assert is_partial == partial


def test_current_month_ignores_unelapsed_previous_days(database):
    add(database, entry("100", "2026-10-05"), entry("1000", "2026-10-25"), entry("90"))
    assert analyze(database).insights == []


def test_full_month_compares_against_full_month(database):
    add(database, entry("100", "2026-09-25"), entry("70", "2026-10-30"))
    response = analyze(database, month=date(2026, 10, 1))
    assert kinds(response) == {InsightType.REVENUE_DROP}
    assert response.insights[0].variation_percentage == Decimal("-30.00")


def test_paid_date_and_business_timezone_are_used(database):
    add(
        database,
        entry("100", "2026-10-05"),
        entry("70", due_date="2020-01-01"),
        entry("10000", paid_at=datetime(2026, 11, 1, 2, tzinfo=UTC)),
    )
    response = analyze(database)
    # The additional payment belongs to October 31 locally, outside the comparable window.
    assert response.insights[0].values.previous_paid_income == Decimal(100)
    assert response.insights[0].values.paid_income == Decimal(70)
    with Session(database) as session:
        response = FinancialInsightsService(session, TZ).analyze(
            business_id=business_a, now=datetime(2026, 11, 1, 2, 59, tzinfo=UTC)
        )
        assert response.reference_date == date(2026, 10, 31)
        assert response.period.end_date == date(2026, 10, 31)


def test_pending_and_cancelled_do_not_change_realized_comparison(database):
    add(
        database,
        entry("100", "2026-10-05"),
        entry("70"),
        entry("99999", "2026-11-20", status=FinancialEntryStatus.PENDING),
        entry("99999", status=FinancialEntryStatus.CANCELLED),
        entry(
            "99999", kind=FinancialType.EXPENSE, status=FinancialEntryStatus.CANCELLED
        ),
    )
    response = analyze(database)
    assert kinds(response) == {InsightType.REVENUE_DROP}
    assert response.insights[0].values.paid_income == Decimal(70)


def test_four_alerts_have_unique_ids_stable_when_values_change(database):
    add(
        database,
        entry("100", "2026-10-05"),
        entry("70"),
        entry("100", "2026-10-05", FinancialType.EXPENSE),
        entry("150", kind=FinancialType.EXPENSE),
        entry("10", "2026-11-01", FinancialType.EXPENSE, FinancialEntryStatus.PENDING),
    )
    first = analyze(database)
    assert len(first.insights) == 4
    assert len({item.id for item in first.insights}) == 4
    before = {item.type: item.id for item in first.insights}
    add(database, entry("1"))
    second = analyze(database)
    assert {item.type: item.id for item in second.insights} == before
    assert second.insights[0].values.paid_income == Decimal(71)


def test_api_uses_jwt_scope_and_rejects_business_override(client, database):
    add(
        database,
        entry("100", "2026-10-05"),
        entry("70"),
        entry("1000", "2026-10-05", business_id=business_b),
        entry("1000", business_id=business_b),
        entry(
            "999",
            "2020-01-01",
            FinancialType.EXPENSE,
            FinancialEntryStatus.PENDING,
            business_b,
        ),
    )
    own = fetch(client)
    assert [item["type"] for item in own["insights"]] == ["REVENUE_DROP"]
    foreign = client.get(ROOT, headers=auth_headers(owner_b))
    assert foreign.status_code == 200
    assert [item["type"] for item in foreign.json()["insights"]] == ["OVERDUE_EXPENSES"]
    assert (
        client.get(
            ROOT, headers=auth_headers(), params={"business_id": str(business_b)}
        ).status_code
        == 422
    )
    assert {item["id"] for item in own["insights"]}.isdisjoint(
        item["id"] for item in foreign.json()["insights"]
    )


@pytest.mark.parametrize(
    "params",
    [
        {"month": "2026-11-02"},
        {"month": "invalid"},
        {"month": "2026-12-01"},
        {"month": "0001-01-01"},
        {"user_id": str(uuid4())},
        {"explain": "invalid"},
    ],
)
def test_invalid_api_parameters(client, params):
    assert client.get(ROOT, headers=auth_headers(), params=params).status_code == 422


@pytest.mark.parametrize(
    ("user", "status"), [(None, 401), (inactive_user, 401), (unassigned_user, 403)]
)
def test_authentication_is_required(client, user, status):
    headers = auth_headers(user) if user else {}
    assert client.get(ROOT, headers=headers).status_code == status


def test_alerts_update_after_real_service_payment(client, database):
    pending = entry("40", status=FinancialEntryStatus.PENDING)
    add(database, entry("100", "2026-10-05"), entry("70"), pending)
    first = fetch(client)
    assert [item["type"] for item in first["insights"]] == ["REVENUE_DROP"]
    with Session(database) as session:
        identifier = session.scalar(
            select(FinancialEntry.id).where(
                FinancialEntry.business_id == business_a,
                FinancialEntry.status == FinancialEntryStatus.PENDING,
            )
        )
        FinancialEntryService(session).pay(
            identifier,
            FinancialEntryPayment(paid_at=NOW),
            business_id=business_a,
            now=NOW,
        )
    assert fetch(client)["insights"] == []


def test_overdue_disappears_after_payment(client, database):
    add(
        database,
        entry("10", "2026-11-01", FinancialType.EXPENSE, FinancialEntryStatus.PENDING),
    )
    assert fetch(client)["insights"][0]["type"] == "OVERDUE_EXPENSES"
    with Session(database) as session:
        identifier = session.scalar(select(FinancialEntry.id))
        FinancialEntryService(session).pay(
            identifier,
            FinancialEntryPayment(paid_at=NOW),
            business_id=business_a,
            now=NOW,
        )
    assert "OVERDUE_EXPENSES" not in {
        item["type"] for item in fetch(client)["insights"]
    }


def test_gemini_failure_returns_200_and_cools_down(client, database):
    add(database, entry("100", "2026-10-05"), entry("70"))
    provider = Mock()
    provider.generate.side_effect = AssistantUnavailableError()
    app.dependency_overrides[get_insights_provider] = lambda: provider
    first = fetch(client)
    second = fetch(client)
    assert first == second
    assert first["insights"][0]["explanation_source"] == "deterministic"
    assert first["insights"][0]["values"]["paid_income"] == "70.00"
    assert first["insights"][0]["suggested_actions"]
    provider.generate.assert_called_once()


def test_no_ai_call_without_alerts_or_when_explanations_disabled(client, database):
    provider = Mock()
    app.dependency_overrides[get_insights_provider] = lambda: provider
    assert fetch(client)["insights"] == []
    add(database, entry("100", "2026-10-05"), entry("70"))
    assert (
        fetch(client, explain="false")["insights"][0]["explanation_source"]
        == "deterministic"
    )
    provider.generate.assert_not_called()


def test_only_three_financial_aggregations_and_no_writes(database):
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "financial_entries" in statement.lower():
            statements.append(statement)

    event.listen(database, "before_cursor_execute", capture)
    try:
        analyze(database)
    finally:
        event.remove(database, "before_cursor_execute", capture)
    assert len(statements) == 3
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement in statements
    )
    assert all("business_id" in statement for statement in statements)


def test_database_failure_is_sanitized_and_session_rolled_back(client):
    session = Mock()
    session.execute.side_effect = OperationalError(
        "private SQL", {}, Exception("private password")
    )
    service = FinancialInsightsService(session, TZ)
    app.dependency_overrides[get_insights_service] = lambda: service
    response = client.get(ROOT, headers=auth_headers())
    assert response.status_code == 503
    assert response.json()["code"] == "financial_insights_unavailable"
    assert "private" not in response.text
    session.rollback.assert_called_once()


def test_explicit_comparison_is_validated_without_changing_old_default(database):
    with Session(database) as session:
        service = FinancialReportService(session, TZ)
        with pytest.raises(InvalidFinancialReportError):
            service.profitability(
                business_id=business_a,
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 13),
                comparison_period=(date(2026, 11, 1), date(2026, 11, 13)),
            )
        with pytest.raises(InvalidFinancialReportError):
            service.profitability(
                business_id=business_a,
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 13),
                comparison_period=(date(2026, 10, 13), date(2026, 10, 1)),
            )


def test_same_overdue_interval_keeps_id_across_selected_months(database):
    add(
        database,
        entry("10", "2026-09-01", FinancialType.EXPENSE, FinancialEntryStatus.PENDING),
    )
    current = analyze(database)
    historical = analyze(database, month=date(2026, 10, 1))
    assert len(current.insights) == len(historical.insights) == 1
    assert current.insights[0].period == historical.insights[0].period
    assert current.insights[0].id == historical.insights[0].id
