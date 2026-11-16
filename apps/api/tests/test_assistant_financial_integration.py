from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_assistant_tools import mock_conversation
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
from test_financial_reports import (
    expected_summary,
    financial_categories,
    income_category_b,
    report_entries,
)

from app.core.config import settings
from app.main import app
from app.modules.assistant.actions import action_repository
from app.modules.assistant.models import AssistantMessage
from app.modules.assistant.providers.base import ProviderReply, ToolCall
from app.modules.assistant.router import get_assistant_provider
from app.modules.financial.exceptions import InvalidFinancialReportError
from app.modules.financial.service import FinancialReportService
from app.modules.financial_entries.models import FinancialEntry

__all__ = [
    "client",
    "database",
    "financial_categories",
    "password_hash",
    "report_entries",
]
CHAT = "/api/v1/assistant/chat"
JANUARY = {"kind": "custom", "start_date": "2026-01-01", "end_date": "2026-01-31"}


class BusinessClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 2, 1, 2, 59, 59, tzinfo=UTC).astimezone(tz)


@pytest.fixture(autouse=True)
def setup_financial_assistant(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", False)
    action_repository.actions.clear()
    with (
        patch("app.modules.assistant.financial_schemas.datetime", BusinessClock),
        patch("app.modules.assistant.service.datetime", BusinessClock),
    ):
        yield
    action_repository.actions.clear()
    app.dependency_overrides.pop(get_assistant_provider, None)


def ask(
    client,
    name,
    arguments=None,
    question="Consulte minhas finanças",
    authentication=None,
    params=None,
    conversation_id=None,
):
    provider, conversation = mock_conversation(
        [
            ProviderReply(calls=[ToolCall(name, arguments or {})]),
            ProviderReply(text="Resultado financeiro consultado no período informado."),
        ]
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    payload = {"message": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    response = client.post(
        CHAT,
        headers=authentication if authentication is not None else auth_headers(),
        json=payload,
        params=params,
    )
    result = (
        conversation.generate.call_args.args[0][0].response
        if conversation.generate.call_count == 2
        else None
    )
    return response, result, provider, conversation


def test_this_month_uses_business_timezone_and_known_paid_pending_totals(
    client, database
):
    before = None
    with Session(database) as session:
        before = [
            (item.id, item.status, item.amount)
            for item in session.scalars(select(FinancialEntry))
        ]
    response, result, provider, _ = ask(
        client,
        "get_financial_summary",
        {"period": {"kind": "this_month"}},
        question="Quanto recebi este mês?",
    )
    assert response.status_code == 200
    assert result["data"] == expected_summary
    assert result["period"]["start_date"] == "2026-01-01"
    assert result["period"]["end_date"] == "2026-01-31"
    assert result["timezone"] == "America/Sao_Paulo"
    assert result["has_data"] is True
    assert (
        "paid_income=receitas recebidas"
        in provider.conversation.call_args.kwargs["system_prompt"]
    )
    assert "2026-01-31" in provider.conversation.call_args.kwargs["system_prompt"]
    with Session(database) as session:
        after = [
            (item.id, item.status, item.amount)
            for item in session.scalars(select(FinancialEntry))
        ]
        assert after == before
        messages = list(
            session.scalars(
                select(AssistantMessage).order_by(AssistantMessage.position)
            )
        )
        assert [item.role for item in messages] == ["user", "assistant"]
    assert not action_repository.actions


@pytest.mark.parametrize(
    "name, extra",
    [
        ("get_cash_flow", {"group_by": "month"}),
        ("get_financial_category_report", {}),
        ("get_financial_profitability", {}),
    ],
)
def test_reports_reuse_known_financial_calculations(client, name, extra):
    response, result, _, _ = ask(client, name, {"period": JANUARY, **extra})
    assert response.status_code == 200
    if name == "get_cash_flow":
        assert result["data"]["total_income"] == "170.30"
        assert result["data"]["total_expenses"] == "57.00"
        assert result["data"]["balance"] == "113.30"
        assert result["data"]["items"][0]["period"] == "2026-01-01"
        assert result["date_basis"] == "paid_at_local"
    elif name == "get_financial_category_report":
        for key, value in expected_summary.items():
            if key != "balance":
                assert result["data"][key] == value
        assert all(
            item["category_name"] != "Foreign expense"
            for item in result["data"]["items"]
        )
    else:
        assert (
            result["data"]["current_period"]["financial_margin_percentage"] == "66.53"
        )
        assert result["data"]["current_period"]["financial_result"] == "113.30"
        assert result["data"]["previous_period"]["paid_income"] == "10.00"


def test_october_question_explicit_dates_are_sent_to_existing_service(client):
    with patch.object(
        FinancialReportService, "summary", autospec=True, wraps=None
    ) as summary:
        from app.modules.financial.schemas import FinancialSummaryResponse

        summary.return_value = FinancialSummaryResponse(
            paid_income=0,
            paid_expenses=0,
            pending_income=0,
            pending_expenses=0,
            balance=0,
        )
        response, result, _, _ = ask(
            client,
            "get_financial_summary",
            {"period": {"kind": "month", "month": 10}},
            question="Quanto gastei em outubro?",
        )
    assert response.status_code == 200
    kwargs = summary.call_args.kwargs
    assert kwargs["business_id"] == business_a
    assert kwargs["start_date"].isoformat() == "2025-10-01"
    assert kwargs["end_date"].isoformat() == "2025-10-31"
    assert result["has_data"] is False


def test_pending_expenses_and_pagination_never_include_paid_cancelled_or_foreign_entries(
    client,
):
    args = {"period": JANUARY, "entry_type": "EXPENSE", "limit": 1}
    response, first, _, _ = ask(
        client,
        "list_pending_financial_entries",
        args,
        question="Quais despesas estão pendentes?",
    )
    assert response.status_code == 200
    assert first["date_basis"] == "due_date"
    assert first["items"][0]["amount"] == "5.00"
    assert first["items"][0]["status"] == "PENDING"
    assert first["has_more"] is True
    _, second, _, _ = ask(
        client, "list_pending_financial_entries", {**args, "offset": 1}
    )
    assert second["items"][0]["amount"] == "12.25"
    assert second["has_more"] is False
    _, all_dates, _, _ = ask(
        client, "list_pending_financial_entries", {"entry_type": "INCOME"}
    )
    assert (
        all_dates["period"]["start_date"] is None
        and all_dates["period"]["end_date"] is None
    )
    assert {item["amount"] for item in all_dates["items"]} == {"30.50", "1.00"}


def test_financial_categories_are_scoped_even_when_foreign_context_is_supplied_in_url(
    client,
):
    response, result, _, _ = ask(
        client, "list_financial_categories", params={"business_id": str(business_b)}
    )
    assert response.status_code == 200
    assert str(income_category_b) not in {item["id"] for item in result["items"]}
    assert {item["type"] for item in result["items"]} == {"INCOME", "EXPENSE"}
    assert result["has_more"] is False


@pytest.mark.parametrize(
    "name",
    [
        "get_financial_summary",
        "get_cash_flow",
        "get_financial_category_report",
        "list_pending_financial_entries",
    ],
)
def test_foreign_category_is_not_queryable(client, name):
    response, result, _, _ = ask(
        client, name, {"period": JANUARY, "category_id": str(income_category_b)}
    )
    assert response.status_code == 200
    assert result["code"] == "financial_category_unavailable"
    assert "data" not in result and "items" not in result


def test_jwt_determines_company_and_query_string_cannot_override_it(client):
    response, result, _, _ = ask(
        client,
        "get_financial_summary",
        {"period": JANUARY},
        authentication=auth_headers(owner_b),
        params={"business_id": str(business_a)},
    )
    assert response.status_code == 200
    assert result["data"]["paid_income"] == "9000.00"
    assert result["data"]["paid_expenses"] == "4000.00"
    assert result["data"]["pending_income"] == "8000.00"


@pytest.mark.parametrize(
    "name",
    [
        "get_financial_summary",
        "get_cash_flow",
        "get_financial_category_report",
        "list_pending_financial_entries",
        "get_financial_profitability",
    ],
)
def test_empty_data_remains_explicit_and_zero_margin_is_not_invented(client, name):
    period = {"kind": "month", "month": 5, "year": 2024}
    response, result, _, _ = ask(client, name, {"period": period})
    assert response.status_code == 200
    assert result["has_data"] is False
    if name == "get_financial_profitability":
        assert result["data"]["current_period"]["financial_margin_percentage"] is None
    elif name in ("get_cash_flow", "get_financial_category_report"):
        assert result["data"]["items"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"business_id": str(business_b)},
        {"user_id": str(owner_b)},
        {
            "period": {
                "kind": "custom",
                "start_date": "2026-02-01",
                "end_date": "2026-01-01",
            }
        },
        {"period": {"kind": "month", "month": 13}},
        {"sql": "SELECT * FROM financial_entries"},
    ],
)
def test_invalid_arguments_are_rejected_before_service_query(client, arguments):
    with patch.object(FinancialReportService, "summary") as summary:
        response, _, _, _ = ask(client, "get_financial_summary", arguments)
    assert response.status_code == 502
    assert response.json()["code"] == "assistant_invalid_tool_call"
    summary.assert_not_called()


@pytest.mark.parametrize(
    "identity, status", [(None, 401), (inactive_user, 401), (unassigned_user, 403)]
)
def test_jwt_required_before_contacting_model(client, identity, status):
    response, _, provider, _ = ask(
        client,
        "get_financial_summary",
        authentication={} if identity is None else auth_headers(identity),
    )
    assert response.status_code == status
    provider.conversation.assert_not_called()


def test_database_failure_is_controlled_and_does_not_expose_details(client):
    with patch.object(
        FinancialReportService,
        "summary",
        side_effect=OperationalError("private SQL", {}, Exception("secret")),
    ):
        response, result, _, conversation = ask(
            client, "get_financial_summary", {"period": JANUARY}
        )
    assert response.status_code == 503
    assert response.json()["code"] == "assistant_database_unavailable"
    assert "private" not in response.text and "secret" not in response.text
    assert result is None and conversation.generate.call_count == 1


def test_business_service_failure_is_a_tool_error_not_fabricated_numbers(client):
    with patch.object(
        FinancialReportService,
        "summary",
        side_effect=InvalidFinancialReportError("private detail"),
    ):
        response, result, _, _ = ask(
            client, "get_financial_summary", {"period": JANUARY}
        )
    assert response.status_code == 200
    assert result["code"] == "financial_query_rejected"
    assert "private" not in str(result) and "data" not in result
