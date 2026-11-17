from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event
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

from app.core.config import settings
from app.modules.financial.exceptions import InvalidFinancialReportError
from app.modules.financial.service import FinancialReportService
from app.modules.financial_categories.models import FinancialCategory
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus

__all__ = ["client", "database", "financial_categories", "password_hash"]
root = "/api/v1/financial"
paths = ["/summary", "/reports/cash-flow", "/reports/categories"]
products_category, rent_category, foreign_expense_category = uuid4(), uuid4(), uuid4()
january = {"start_date": "2026-01-01", "end_date": "2026-01-31"}
expected_summary = {
    "paid_income": "170.30",
    "paid_expenses": "57.00",
    "balance": "113.30",
    "pending_income": "30.50",
    "pending_expenses": "17.25",
}


def sqlite_timezone(zone, value):
    # SQLite drops tzinfo; disposable fixtures store payment timestamps in UTC.
    if value is None:
        return None
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(ZoneInfo(zone)).replace(tzinfo=None).isoformat(" ")


def payment(
    amount,
    category_id,
    entry_type="INCOME",
    paid_at="2026-01-05T12:00:00Z",
    due_date="2025-12-10",
    business_id=business_a,
):
    return FinancialEntry(
        business_id=business_id,
        category_id=category_id,
        type=entry_type,
        description="Payment",
        amount=Decimal(amount),
        due_date=date.fromisoformat(due_date),
        status=FinancialEntryStatus.PAID,
        paid_at=datetime.fromisoformat(paid_at).astimezone(UTC),
    )


@pytest.fixture(autouse=True)
def report_entries(database, financial_categories, monkeypatch):
    monkeypatch.setattr(settings, "BUSINESS_TIMEZONE", "America/Sao_Paulo")
    with database.connect() as connection:
        connection.connection.driver_connection.create_function(
            "timezone", 2, sqlite_timezone
        )
    with Session(database) as session:
        session.add_all(
            [
                FinancialCategory(
                    id=products_category,
                    business_id=business_a,
                    name="Products",
                    type="INCOME",
                ),
                FinancialCategory(
                    id=rent_category,
                    business_id=business_a,
                    name="Rent",
                    type="EXPENSE",
                ),
                FinancialCategory(
                    id=foreign_expense_category,
                    business_id=business_b,
                    name="Foreign expense",
                    type="EXPENSE",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                payment("100.10", income_category_a),
                payment("0.20", income_category_a, paid_at="2026-01-05T14:00:00Z"),
                payment("50.00", products_category, paid_at="2026-01-06T13:00:00Z"),
                payment(
                    "40.25",
                    expense_category_a,
                    "EXPENSE",
                    paid_at="2026-01-05T10:00:00Z",
                ),
                payment(
                    "9.75", rent_category, "EXPENSE", paid_at="2026-01-31T23:59:00Z"
                ),
                payment(
                    "7.00", rent_category, "EXPENSE", paid_at="2026-01-01T03:00:00Z"
                ),
                payment(
                    "200",
                    income_category_a,
                    paid_at="2026-02-01T03:00:00Z",
                    due_date="2026-01-15",
                ),
                payment(
                    "10",
                    income_category_a,
                    paid_at="2026-01-01T02:59:59Z",
                    due_date="2026-01-01",
                ),
                payment(
                    "20",
                    income_category_a,
                    paid_at="2026-02-01T02:59:59Z",
                    due_date="2026-02-01",
                ),
                payment("9000", income_category_b, business_id=business_b),
                payment(
                    "4000", foreign_expense_category, "EXPENSE", business_id=business_b
                ),
            ]
        )
        for amount, category_id, movement_type, due, status, business_id in [
            ("30.50", income_category_a, "INCOME", "2026-01-10", "PENDING", business_a),
            ("1", income_category_a, "INCOME", "2026-02-01", "PENDING", business_a),
            (
                "12.25",
                expense_category_a,
                "EXPENSE",
                "2026-01-10",
                "PENDING",
                business_a,
            ),
            ("5", rent_category, "EXPENSE", "2026-01-31", "PENDING", business_a),
            ("999", income_category_a, "INCOME", "2026-01-10", "CANCELLED", business_a),
            (
                "1000",
                expense_category_a,
                "EXPENSE",
                "2026-01-10",
                "CANCELLED",
                business_a,
            ),
            ("8000", income_category_b, "INCOME", "2026-01-10", "PENDING", business_b),
            (
                "3000",
                foreign_expense_category,
                "EXPENSE",
                "2026-01-10",
                "PENDING",
                business_b,
            ),
        ]:
            session.add(
                FinancialEntry(
                    business_id=business_id,
                    category_id=category_id,
                    type=movement_type,
                    description="Entry",
                    amount=Decimal(amount),
                    due_date=date.fromisoformat(due),
                    status=status,
                )
            )
        session.commit()


def report(client, path, **params):
    response = client.get(root + path, headers=auth_headers(), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_separates_paid_pending_cancelled_and_payment_date_from_due_date(
    client,
):
    assert report(client, "/summary", **january) == expected_summary
    assert report(client, "/summary") == {
        "paid_income": "380.30",
        "paid_expenses": "57.00",
        "balance": "323.30",
        "pending_income": "31.50",
        "pending_expenses": "17.25",
    }


def test_daily_cash_flow_uses_actual_payment_local_day_and_keeps_order(client):
    response = report(client, "/reports/cash-flow", **january)
    assert response == {
        "group_by": "day",
        "total_income": "170.30",
        "total_expenses": "57.00",
        "balance": "113.30",
        "items": [
            {
                "period": "2026-01-01",
                "income": "0.00",
                "expenses": "7.00",
                "balance": "-7.00",
            },
            {
                "period": "2026-01-05",
                "income": "100.30",
                "expenses": "40.25",
                "balance": "60.05",
            },
            {
                "period": "2026-01-06",
                "income": "50.00",
                "expenses": "0.00",
                "balance": "50.00",
            },
            {
                "period": "2026-01-31",
                "income": "20.00",
                "expenses": "9.75",
                "balance": "10.25",
            },
        ],
    }


def test_monthly_cash_flow_and_partial_month_filter(client):
    response = report(client, "/reports/cash-flow", group_by="month")
    assert response["items"] == [
        {
            "period": "2025-12-01",
            "income": "10.00",
            "expenses": "0.00",
            "balance": "10.00",
        },
        {
            "period": "2026-01-01",
            "income": "170.30",
            "expenses": "57.00",
            "balance": "113.30",
        },
        {
            "period": "2026-02-01",
            "income": "200.00",
            "expenses": "0.00",
            "balance": "200.00",
        },
    ]
    partial = report(
        client,
        "/reports/cash-flow",
        group_by="month",
        start_date="2026-01-05",
        end_date="2026-01-05",
    )
    assert partial["items"] == [
        {
            "period": "2026-01-01",
            "income": "100.30",
            "expenses": "40.25",
            "balance": "60.05",
        }
    ]


def test_category_totals_and_percentages_use_separate_type_and_status_denominators(
    client,
):
    response = report(client, "/reports/categories", **january)
    assert {key: response[key] for key in expected_summary if key != "balance"} == {
        key: value for key, value in expected_summary.items() if key != "balance"
    }
    items = {item["category_id"]: item for item in response["items"]}
    assert items[str(income_category_a)] == {
        "category_id": str(income_category_a),
        "category_name": "Vendas",
        "type": "INCOME",
        "paid_total": "120.30",
        "pending_total": "30.50",
        "paid_percentage": "70.64",
        "pending_percentage": "100.00",
    }
    assert items[str(products_category)]["paid_percentage"] == "29.36"
    assert items[str(products_category)]["pending_percentage"] == "0.00"
    assert items[str(expense_category_a)]["paid_percentage"] == "70.61"
    assert items[str(expense_category_a)]["pending_percentage"] == "71.01"
    assert items[str(rent_category)]["paid_percentage"] == "29.39"
    assert items[str(rent_category)]["pending_percentage"] == "28.99"


@pytest.mark.parametrize(
    "entry_type,paid,pending,count",
    [
        ("INCOME", "170.30", "30.50", 2),
        ("EXPENSE", "57.00", "17.25", 2),
    ],
)
def test_category_type_filter_does_not_mix_income_expense_percentages(
    client, entry_type, paid, pending, count
):
    response = report(client, "/reports/categories", **january, type=entry_type)
    assert len(response["items"]) == count
    assert all(item["type"] == entry_type for item in response["items"])
    assert (
        response["paid_income" if entry_type == "INCOME" else "paid_expenses"] == paid
    )
    assert (
        response["pending_income" if entry_type == "INCOME" else "pending_expenses"]
        == pending
    )
    assert (
        response["paid_expenses" if entry_type == "INCOME" else "paid_income"] == "0.00"
    )


def test_category_filter_applies_to_all_reports(client):
    params = {**january, "category_id": str(products_category)}
    assert report(client, "/summary", **params) == {
        "paid_income": "50.00",
        "paid_expenses": "0.00",
        "balance": "50.00",
        "pending_income": "0.00",
        "pending_expenses": "0.00",
    }
    cash = report(client, "/reports/cash-flow", **params)
    assert cash["total_income"] == "50.00" and len(cash["items"]) == 1
    categories = report(client, "/reports/categories", **params)
    assert (
        len(categories["items"]) == 1
        and categories["items"][0]["paid_percentage"] == "100.00"
    )
    assert categories["items"][0]["category_id"] == str(products_category)


@pytest.mark.parametrize("path", paths)
def test_empty_periods_return_zero_totals_and_no_buckets(client, path):
    response = report(client, path, start_date="2030-01-01", end_date="2030-01-31")
    assert all(
        value == "0.00"
        for key, value in response.items()
        if key not in {"group_by", "items"}
    )
    if path != "/summary":
        assert response["items"] == []


@pytest.mark.parametrize("path", paths)
def test_pending_only_period_does_not_enter_cash_and_handles_zero_paid_denominator(
    client, path
):
    response = report(client, path, start_date="2026-01-10", end_date="2026-01-10")
    if path == "/reports/cash-flow":
        assert response["items"] == [] and response["total_income"] == "0.00"
    else:
        assert response["paid_income"] == response["paid_expenses"] == "0.00"
        assert (
            response["pending_income"] == "30.50"
            and response["pending_expenses"] == "12.25"
        )
        if path.endswith("categories"):
            assert all(
                item["paid_percentage"] == "0.00"
                and item["pending_percentage"] == "100.00"
                for item in response["items"]
            )


@pytest.mark.parametrize(
    "params,income,expenses",
    [
        ({"start_date": "2026-02-01"}, "200.00", "0.00"),
        ({"end_date": "2025-12-31"}, "10.00", "0.00"),
        ({"start_date": "2026-01-31", "end_date": "2026-01-31"}, "20.00", "9.75"),
    ],
)
def test_open_and_inclusive_periods(client, params, income, expenses):
    summary = report(client, "/summary", **params)
    cash = report(client, "/reports/cash-flow", **params)
    assert summary["paid_income"] == cash["total_income"] == income
    assert summary["paid_expenses"] == cash["total_expenses"] == expenses


@pytest.mark.parametrize("path", paths)
def test_company_is_only_taken_from_jwt_and_foreign_categories_reveal_nothing(
    client, path
):
    own = report(client, path, **january)
    assert report(client, path, **january, business_id=str(business_b)) == own
    for identifier in (income_category_b, uuid4()):
        empty = report(client, path, **january, category_id=str(identifier))
        assert all(
            value == "0.00"
            for key, value in empty.items()
            if key not in {"items", "group_by"}
        )
        if path != "/summary":
            assert empty["items"] == []
    foreign = client.get(root + path, headers=auth_headers(owner_b), params=january)
    assert foreign.status_code == 200
    data = foreign.json()
    if path == "/reports/cash-flow":
        assert data["total_income"] == "9000.00" and data["total_expenses"] == "4000.00"
    else:
        assert data["paid_income"] == "9000.00" and data["paid_expenses"] == "4000.00"
        assert (
            data["pending_income"] == "8000.00"
            and data["pending_expenses"] == "3000.00"
        )


@pytest.mark.parametrize("path", paths)
@pytest.mark.parametrize(
    "identity,status",
    [(None, 401), ("invalid", 401), (inactive_user, 401), (unassigned_user, 403)],
)
def test_reports_require_active_authenticated_user_with_business(
    client, path, identity, status
):
    headers = (
        {}
        if identity is None
        else {"Authorization": "Bearer invalid"}
        if identity == "invalid"
        else auth_headers(identity)
    )
    assert client.get(root + path, headers=headers).status_code == status


@pytest.mark.parametrize("path", paths)
@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-02-01", "end_date": "2026-01-01"},
        {"start_date": "invalid"},
        {"end_date": "2026-02-30"},
        {"category_id": "invalid"},
    ],
)
def test_invalid_periods_and_category_ids(client, path, params):
    assert (
        client.get(root + path, headers=auth_headers(), params=params).status_code
        == 422
    )


@pytest.mark.parametrize(
    "path,params",
    [
        ("/reports/cash-flow", {"group_by": "week"}),
        ("/reports/categories", {"type": "OTHER"}),
    ],
)
def test_invalid_grouping_and_type(client, path, params):
    assert (
        client.get(root + path, headers=auth_headers(), params=params).status_code
        == 422
    )


def test_recurring_templates_are_not_counted_and_generated_entries_count_only_once(
    client,
):
    before = report(client, "/summary", **january)
    response = client.post(
        "/api/v1/recurring-entries",
        headers=auth_headers(),
        json={
            "category_id": str(expense_category_a),
            "type": "EXPENSE",
            "description": "Subscription",
            "amount": "13.37",
            "due_day": 15,
            "start_date": "2026-01-01",
        },
    )
    assert response.status_code == 201
    recurrence_id = response.json()["id"]
    assert report(client, "/summary", **january) == before
    period = {"start_month": "2026-01-01", "end_month": "2026-03-01"}
    first = client.post(
        f"/api/v1/recurring-entries/{recurrence_id}/generate",
        headers=auth_headers(),
        json=period,
    )
    assert first.status_code == 200
    generated = first.json()["created_entries"]
    assert len(generated) == 3
    second = client.post(
        f"/api/v1/recurring-entries/{recurrence_id}/generate",
        headers=auth_headers(),
        json=period,
    )
    assert second.json()["created_entries"] == []
    assert report(client, "/summary", **january)["pending_expenses"] == "30.62"
    paid = client.post(
        f"/api/v1/financial-entries/{generated[0]['id']}/pay",
        headers=auth_headers(),
        json={"paid_at": "2026-01-20T12:00:00Z"},
    )
    assert paid.status_code == 200
    assert (
        client.delete(
            f"/api/v1/recurring-entries/{recurrence_id}", headers=auth_headers()
        ).status_code
        == 204
    )
    summary = report(client, "/summary", **january)
    cash = report(client, "/reports/cash-flow", **january)
    categories = report(client, "/reports/categories", **january)
    assert (
        summary["paid_expenses"]
        == cash["total_expenses"]
        == categories["paid_expenses"]
        == "70.37"
    )
    assert summary["pending_expenses"] == before["pending_expenses"]
    assert report(client, "/summary")["pending_expenses"] == "43.99"


@pytest.mark.parametrize("method", ["summary", "cash_flow", "categories"])
def test_reports_are_read_only_and_use_one_aggregate_query(database, method):
    with Session(database) as session:
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        with (
            patch.object(
                session, "commit", side_effect=AssertionError("Read committed")
            ),
            patch.object(
                session, "rollback", side_effect=AssertionError("Read rolled back")
            ),
        ):
            event.listen(database, "before_cursor_execute", capture)
            try:
                result = getattr(
                    FinancialReportService(session, ZoneInfo("America/Sao_Paulo")),
                    method,
                )(
                    business_id=business_a,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 31),
                )
            finally:
                event.remove(database, "before_cursor_execute", capture)
        assert result
        assert len(statements) == 1
        assert "sum(" in statements[0].lower() and "financial_entries" in statements[0]
        assert "JOIN recurring_entries" not in statements[0]


@pytest.mark.parametrize("method", ["summary", "cash_flow", "categories"])
def test_service_validates_reversed_period_without_query(database, method):
    with (
        Session(database) as session,
        patch.object(
            session, "execute", side_effect=AssertionError("Queried invalid period")
        ),
        pytest.raises(InvalidFinancialReportError),
    ):
        getattr(FinancialReportService(session, ZoneInfo("UTC")), method)(
            business_id=business_a,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 1, 1),
        )


def test_cash_service_validates_grouping(database):
    with Session(database) as session, pytest.raises(InvalidFinancialReportError):
        FinancialReportService(session, ZoneInfo("UTC")).cash_flow(
            business_id=business_a, group_by="week"
        )


def test_decimal_balance_and_percentages_have_no_binary_float_artifacts(database):
    with Session(database) as session:
        result = FinancialReportService(session, ZoneInfo("America/Sao_Paulo")).summary(
            business_id=business_a,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        assert result.paid_income == Decimal("170.30") and result.balance == Decimal(
            "113.30"
        )
        assert isinstance(result.balance, Decimal)
