from datetime import date
from decimal import Decimal
from unittest.mock import patch
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
)
from test_financial_reports import january, payment, report_entries

from app.modules.financial.exceptions import InvalidFinancialReportError
from app.modules.financial.schemas import CashFlowGrouping
from app.modules.financial.service import FinancialReportService

__all__ = [
    "client",
    "database",
    "financial_categories",
    "password_hash",
    "report_entries",
]
path = "/api/v1/financial/reports/profitability"


def profitability(client, headers=None, **params):
    response = client.get(
        path, headers=headers or auth_headers(), params=params or january
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_payments(database, *entries):
    with Session(database) as session:
        session.add_all(entries)
        session.commit()


def test_positive_financial_metrics_and_comparison_with_previous_calendar_month(client):
    data = profitability(client)
    assert data["current_period"] == {
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "paid_income": "170.30",
        "paid_expenses": "57.00",
        "financial_result": "113.30",
        "financial_margin_percentage": "66.53",
    }
    assert data["previous_period"] == {
        "start_date": "2025-12-01",
        "end_date": "2025-12-31",
        "paid_income": "10.00",
        "paid_expenses": "0.00",
        "financial_result": "10.00",
        "financial_margin_percentage": "100.00",
    }
    assert data["comparison"] == {
        "paid_income_change": "160.30",
        "paid_income_change_percentage": "1603.00",
        "paid_expenses_change": "57.00",
        "paid_expenses_change_percentage": None,
        "financial_result_change": "103.30",
        "financial_result_change_percentage": "1033.00",
        "financial_margin_change_percentage_points": "-33.47",
    }
    assert data["monthly_evolution"] == [
        {
            "period": "2026-01-01",
            "paid_income": "170.30",
            "paid_expenses": "57.00",
            "financial_result": "113.30",
            "financial_margin_percentage": "66.53",
        }
    ]


def test_february_compares_against_entire_january_and_monthly_deltas(client):
    data = profitability(client, start_date="2026-02-01", end_date="2026-02-28")
    assert data["previous_period"]["start_date"] == "2026-01-01"
    assert data["previous_period"]["end_date"] == "2026-01-31"
    assert data["current_period"]["financial_result"] == "200.00"
    assert data["comparison"] == {
        "paid_income_change": "29.70",
        "paid_income_change_percentage": "17.44",
        "paid_expenses_change": "-57.00",
        "paid_expenses_change_percentage": "-100.00",
        "financial_result_change": "86.70",
        "financial_result_change_percentage": "76.52",
        "financial_margin_change_percentage_points": "33.47",
    }


def test_negative_result_and_margin_are_not_clamped_to_zero(client, database):
    add_payments(
        database,
        payment("200", expense_category_a, "EXPENSE", paid_at="2026-01-15T12:00:00Z"),
    )
    data = profitability(client)
    assert data["current_period"]["paid_expenses"] == "257.00"
    assert data["current_period"]["financial_result"] == "-86.70"
    assert data["current_period"]["financial_margin_percentage"] == "-50.91"
    assert data["comparison"]["financial_result_change_percentage"] == "-967.00"
    assert data["monthly_evolution"][0]["financial_margin_percentage"] == "-50.91"


def test_expense_only_period_keeps_negative_result_and_undefined_margin(
    client, database
):
    add_payments(
        database,
        payment("42.25", expense_category_a, "EXPENSE", paid_at="2026-03-15T12:00:00Z"),
    )
    data = profitability(client, start_date="2026-03-01", end_date="2026-03-31")
    assert data["current_period"]["paid_income"] == "0.00"
    assert data["current_period"]["financial_result"] == "-42.25"
    assert data["current_period"]["financial_margin_percentage"] is None
    assert data["monthly_evolution"][0]["financial_margin_percentage"] is None
    assert data["comparison"]["financial_result_change_percentage"] == "-121.13"
    assert data["comparison"]["financial_margin_change_percentage_points"] is None


def test_break_even_has_zero_margin_when_income_exists(client, database):
    add_payments(
        database,
        payment("100", income_category_a, paid_at="2026-05-15T12:00:00Z"),
        payment("100", expense_category_a, "EXPENSE", paid_at="2026-05-15T12:00:00Z"),
    )
    data = profitability(client, start_date="2026-05-01", end_date="2026-05-31")
    assert data["current_period"]["financial_result"] == "0.00"
    assert data["current_period"]["financial_margin_percentage"] == "0.00"
    assert data["comparison"]["financial_result_change_percentage"] is None


@pytest.mark.parametrize(
    "current_expenses,result,change",
    [("150", "-50.00", "50.00"), ("250", "-150.00", "-50.00")],
)
def test_comparison_against_negative_result_preserves_improvement_direction(
    client, database, current_expenses, result, change
):
    add_payments(
        database,
        payment("100", income_category_a, paid_at="2026-03-15T12:00:00Z"),
        payment("200", expense_category_a, "EXPENSE", paid_at="2026-03-15T12:00:00Z"),
        payment("100", income_category_a, paid_at="2026-04-15T12:00:00Z"),
        payment(
            current_expenses,
            expense_category_a,
            "EXPENSE",
            paid_at="2026-04-15T12:00:00Z",
        ),
    )
    data = profitability(client, start_date="2026-04-01", end_date="2026-04-30")
    assert data["previous_period"]["financial_result"] == "-100.00"
    assert data["current_period"]["financial_result"] == result
    assert data["comparison"]["financial_result_change_percentage"] == change
    assert data["comparison"]["financial_margin_change_percentage_points"] == change


def test_empty_periods_have_zero_values_null_margins_and_all_calendar_months(client):
    data = profitability(client, start_date="2027-07-01", end_date="2027-09-30")
    for key in ("current_period", "previous_period"):
        assert (
            data[key]["paid_income"]
            == data[key]["paid_expenses"]
            == data[key]["financial_result"]
            == "0.00"
        )
        assert data[key]["financial_margin_percentage"] is None
    assert [item["period"] for item in data["monthly_evolution"]] == [
        "2027-07-01",
        "2027-08-01",
        "2027-09-01",
    ]
    assert all(
        item["financial_result"] == "0.00"
        and item["financial_margin_percentage"] is None
        for item in data["monthly_evolution"]
    )
    assert data["comparison"]["paid_income_change_percentage"] is None
    assert data["comparison"]["financial_result_change"] == "0.00"


def test_monthly_evolution_and_overall_margin_use_actual_period_totals(client):
    data = profitability(client, start_date="2026-01-01", end_date="2026-03-31")
    assert data["current_period"]["paid_income"] == "370.30"
    assert data["current_period"]["financial_result"] == "313.30"
    assert data["current_period"]["financial_margin_percentage"] == "84.61"
    assert [
        item["financial_margin_percentage"] for item in data["monthly_evolution"]
    ] == ["66.53", "100.00", None]
    assert data["previous_period"]["start_date"] == "2025-10-01"


def test_partial_period_does_not_count_payments_outside_selected_days(client):
    data = profitability(client, start_date="2026-01-05", end_date="2026-01-06")
    assert data["previous_period"]["start_date"] == "2026-01-03"
    assert data["previous_period"]["end_date"] == "2026-01-04"
    assert data["current_period"]["paid_income"] == "150.30"
    assert data["current_period"]["paid_expenses"] == "40.25"
    assert data["monthly_evolution"][0]["paid_income"] == "150.30"
    assert data["monthly_evolution"][0]["period"] == "2026-01-01"


@pytest.mark.parametrize(
    "start,end,previous_start,previous_end",
    [
        ("2026-04-01", "2026-04-30", "2026-03-01", "2026-03-31"),
        ("2024-02-01", "2024-02-29", "2024-01-01", "2024-01-31"),
        ("2024-02-01", "2024-02-28", "2024-01-04", "2024-01-31"),
        ("2026-02-10", "2026-02-20", "2026-01-30", "2026-02-09"),
        ("2026-01-01", "2026-03-31", "2025-10-01", "2025-12-31"),
        ("2026-01-31", "2026-01-31", "2026-01-30", "2026-01-30"),
        ("9999-12-01", "9999-12-31", "9999-11-01", "9999-11-30"),
    ],
)
def test_equivalent_period_calendar_and_day_boundaries(
    client, start, end, previous_start, previous_end
):
    data = profitability(client, start_date=start, end_date=end)
    assert data["previous_period"]["start_date"] == previous_start
    assert data["previous_period"]["end_date"] == previous_end


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"start_date": "2026-01-01"},
        {"end_date": "2026-01-31"},
        {"start_date": "2026-02-01", "end_date": "2026-01-01"},
        {"start_date": "bad", "end_date": "2026-01-31"},
        {"start_date": "2026-01-01", "end_date": "2026-02-30"},
        {"start_date": "0001-01-01", "end_date": "0001-01-31"},
        {"start_date": "0001-01-10", "end_date": "0001-02-10"},
    ],
)
def test_required_dates_invalid_periods_and_previous_period_underflow(client, params):
    assert client.get(path, headers=auth_headers(), params=params).status_code == 422


@pytest.mark.parametrize(
    "identity,status",
    [(None, 401), ("invalid", 401), (inactive_user, 401), (unassigned_user, 403)],
)
def test_profitability_requires_active_jwt_and_business(client, identity, status):
    headers = (
        {}
        if identity is None
        else {"Authorization": "Bearer invalid"}
        if identity == "invalid"
        else auth_headers(identity)
    )
    assert client.get(path, headers=headers, params=january).status_code == status


def test_company_isolation_applies_to_both_periods_and_monthly_series(client):
    own = profitability(client)
    forged = profitability(client, **january, business_id=str(business_b))
    assert forged == own
    other = profitability(client, headers=auth_headers(owner_b))
    assert other["current_period"]["paid_income"] == "9000.00"
    assert other["current_period"]["paid_expenses"] == "4000.00"
    assert other["current_period"]["financial_result"] == "5000.00"
    assert other["current_period"]["financial_margin_percentage"] == "55.56"
    assert other["previous_period"]["paid_income"] == "0.00"
    assert other["monthly_evolution"][0]["paid_income"] == "9000.00"


def test_only_paid_recurring_entries_are_included_once(client):
    before = profitability(client)
    created = client.post(
        "/api/v1/recurring-entries",
        headers=auth_headers(),
        json={
            "category_id": str(income_category_a),
            "type": "INCOME",
            "description": "Monthly fee",
            "amount": "13.37",
            "due_day": 15,
            "start_date": "2026-01-01",
        },
    )
    assert created.status_code == 201
    recurrence_id = created.json()["id"]
    assert profitability(client) == before
    period = {"start_month": "2026-01-01", "end_month": "2026-03-01"}
    generated = client.post(
        f"/api/v1/recurring-entries/{recurrence_id}/generate",
        headers=auth_headers(),
        json=period,
    )
    assert generated.status_code == 200
    assert profitability(client) == before
    repeated = client.post(
        f"/api/v1/recurring-entries/{recurrence_id}/generate",
        headers=auth_headers(),
        json=period,
    )
    assert repeated.json()["created_entries"] == []
    entry_id = generated.json()["created_entries"][0]["id"]
    assert (
        client.post(
            f"/api/v1/financial-entries/{entry_id}/pay",
            headers=auth_headers(),
            json={"paid_at": "2026-01-20T12:00:00Z"},
        ).status_code
        == 200
    )
    data = profitability(client)
    assert data["current_period"]["paid_income"] == "183.67"
    assert data["current_period"]["financial_result"] == "126.67"
    assert data["monthly_evolution"][0]["paid_income"] == "183.67"
    assert data["previous_period"] == before["previous_period"]


def test_profitability_reuses_monthly_cash_flow_with_two_bounded_read_queries(database):
    with Session(database) as session:
        service = FinancialReportService(session, ZoneInfo("America/Sao_Paulo"))
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        with (
            patch.object(service, "cash_flow", wraps=service.cash_flow) as cash_flow,
            patch.object(
                session, "commit", side_effect=AssertionError("Read committed")
            ),
            patch.object(
                session, "rollback", side_effect=AssertionError("Read rolled back")
            ),
        ):
            event.listen(database, "before_cursor_execute", capture)
            try:
                result = service.profitability(
                    business_id=business_a,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 3, 31),
                )
            finally:
                event.remove(database, "before_cursor_execute", capture)
        assert cash_flow.call_count == 2
        assert all(
            call.kwargs["group_by"] == CashFlowGrouping.MONTH
            for call in cash_flow.call_args_list
        )
        assert len(statements) == 2 and all(
            "sum(" in statement.lower() for statement in statements
        )
        assert result.current_period.financial_result == Decimal("313.30")
        assert isinstance(result.current_period.financial_margin_percentage, Decimal)


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 2, 1), date(2026, 1, 1)),
        (date.min, date(1, 1, 31)),
        (date(1, 1, 10), date(1, 2, 10)),
    ],
)
def test_invalid_periods_are_rejected_before_any_database_query(database, start, end):
    with (
        Session(database) as session,
        patch.object(
            session, "execute", side_effect=AssertionError("Queried invalid period")
        ),
        pytest.raises(InvalidFinancialReportError),
    ):
        FinancialReportService(session, ZoneInfo("UTC")).profitability(
            business_id=business_a,
            start_date=start,
            end_date=end,
        )
