from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.modules.assistant.exceptions import AssistantToolCallError
from app.modules.assistant.financial_schemas import (
    FINANCIAL_TOOL_SCHEMAS,
    FinancialPeriod,
    InvalidFinancialPeriodError,
)
from app.modules.assistant.providers.base import ToolCall
from app.modules.assistant.tools import AssistantTools
from app.modules.assistant.tools.financial import FinancialTools
from app.modules.financial_categories.exceptions import FinancialCategoryNotFoundError

ZONE = ZoneInfo("America/Sao_Paulo")


@pytest.mark.parametrize(
    "selection, now, expected",
    [
        ({"kind": "this_month"}, "2026-11-01T01:00:00Z", ("2026-10-01", "2026-10-31")),
        ({"kind": "last_month"}, "2026-01-10T12:00:00Z", ("2025-12-01", "2025-12-31")),
        (
            {"kind": "month", "month": 2, "year": 2028},
            "2026-01-10T12:00:00Z",
            ("2028-02-01", "2028-02-29"),
        ),
        (
            {"kind": "month", "month": 10},
            "2026-01-10T12:00:00Z",
            ("2025-10-01", "2025-10-31"),
        ),
        (
            {"kind": "month", "month": 10},
            "2026-11-12T12:00:00Z",
            ("2026-10-01", "2026-10-31"),
        ),
        ({"kind": "today"}, "2026-11-01T01:00:00Z", ("2026-10-31", "2026-10-31")),
        ({"kind": "yesterday"}, "2026-03-01T12:00:00Z", ("2026-02-28", "2026-02-28")),
        ({"kind": "last_7_days"}, "2026-01-03T12:00:00Z", ("2025-12-28", "2026-01-03")),
        (
            {"kind": "last_30_days"},
            "2026-01-03T12:00:00Z",
            ("2025-12-05", "2026-01-03"),
        ),
        ({"kind": "last_year"}, "2026-01-03T12:00:00Z", ("2025-01-01", "2025-12-31")),
        ({"kind": "this_year"}, "2028-01-03T12:00:00Z", ("2028-01-01", "2028-12-31")),
        (
            {"kind": "custom", "start_date": "2026-10-05", "end_date": "2026-10-05"},
            "2026-11-12T12:00:00Z",
            ("2026-10-05", "2026-10-05"),
        ),
    ],
)
def test_periods_use_business_calendar(
    selection: dict, now: str, expected: tuple[str, str]
) -> None:
    resolved = FinancialPeriod.model_validate(selection).resolve(
        ZONE, now=datetime.fromisoformat(now)
    )
    assert resolved == tuple(date.fromisoformat(item) for item in expected)


@pytest.mark.parametrize(
    "selection",
    [
        {"kind": "custom", "start_date": "2026-10-01"},
        {"kind": "custom", "start_date": "2026-10-02", "end_date": "2026-10-01"},
        {"kind": "this_month", "start_date": "2026-10-01"},
        {"kind": "month"},
        {"kind": "month", "month": 13},
        {"kind": "month", "month": True},
        {"kind": "month", "month": 2, "year": 0},
        {"kind": "month", "month": "10"},
        {"kind": "today", "year": 2026},
        {"kind": "custom", "start_date": "2026-02-30", "end_date": "2026-03-01"},
        {"kind": "today", "business_id": str(uuid4())},
        {"kind": "today", "timezone": "UTC"},
    ],
)
def test_period_rejects_invalid_or_ambiguous_parameters(selection: dict) -> None:
    with pytest.raises(ValidationError):
        FinancialPeriod.model_validate(selection)


def test_all_time_is_explicit_and_calendar_underflow_is_controlled() -> None:
    assert FinancialPeriod(kind="all_time").resolve(ZONE) == (None, None)
    with pytest.raises(InvalidFinancialPeriodError):
        FinancialPeriod(kind="last_year").resolve(
            ZoneInfo("UTC"), now=datetime(1, 1, 1, tzinfo=UTC)
        )


@pytest.fixture
def tools() -> AssistantTools:
    return AssistantTools(
        uuid4(),
        Mock(),
        Mock(),
        Mock(),
        user_id=uuid4(),
        financial_tools=FinancialTools(Mock(), Mock(), Mock(), ZONE),
    )


@pytest.mark.parametrize("name", list(FINANCIAL_TOOL_SCHEMAS))
def test_financial_schemas_never_accept_business_or_user_from_model(
    tools: AssistantTools, name: str
) -> None:
    for key in ("business_id", "user_id", "timezone", "sql"):
        with pytest.raises(AssistantToolCallError):
            tools.execute(ToolCall(name, {key: str(uuid4())}))
    tools.financial_tools.reports.summary.assert_not_called()
    tools.financial_tools.entries.list.assert_not_called()


def test_financial_tools_are_only_registered_when_services_are_injected(
    tools: AssistantTools,
) -> None:
    names = {item["name"] for item in tools.declarations()}
    assert set(FINANCIAL_TOOL_SCHEMAS) <= names
    tools.financial_tools = None
    assert not set(FINANCIAL_TOOL_SCHEMAS) & {
        item["name"] for item in tools.declarations()
    }
    with pytest.raises(AssistantToolCallError):
        tools.execute(ToolCall("get_financial_summary", {}))


@pytest.mark.parametrize(
    "name",
    [
        "create_financial_entry",
        "pay_financial_entry",
        "delete_financial_entry",
        "financial_insights",
    ],
)
def test_no_financial_writing_or_insight_tool_exists(
    tools: AssistantTools, name: str
) -> None:
    with pytest.raises(AssistantToolCallError):
        tools.execute(ToolCall(name, {}))


def test_pending_filter_and_pagination_are_fixed_by_backend(
    tools: AssistantTools,
) -> None:
    tools.financial_tools.entries.list.return_value = []
    result = tools.execute(
        ToolCall(
            "list_pending_financial_entries", {"entry_type": "EXPENSE", "limit": 1}
        )
    )
    assert result.response["items"] == [] and result.response["has_data"] is False
    kwargs = tools.financial_tools.entries.list.call_args.kwargs
    assert kwargs["business_id"] == tools.business_id
    assert kwargs["status"].value == "PENDING"
    assert kwargs["entry_type"].value == "EXPENSE"
    assert kwargs["start_date"] is None and kwargs["end_date"] is None
    assert kwargs["limit"] == 2


def test_category_lookup_is_scoped_and_error_does_not_leak_details(
    tools: AssistantTools,
) -> None:
    category_id = uuid4()
    tools.financial_tools.categories.get_by_id.side_effect = (
        FinancialCategoryNotFoundError("private database detail")
    )
    result = tools.execute(
        ToolCall("get_financial_summary", {"category_id": str(category_id)})
    )
    assert result.response["code"] == "financial_category_unavailable"
    assert "private" not in str(result.response)
    tools.financial_tools.categories.get_by_id.assert_called_once_with(
        category_id, business_id=tools.business_id
    )
    tools.financial_tools.reports.summary.assert_not_called()


@pytest.mark.parametrize(
    "name, period",
    [
        ("get_cash_flow", {"kind": "all_time"}),
        ("get_financial_profitability", {"kind": "all_time"}),
        (
            "get_cash_flow",
            {"kind": "custom", "start_date": "2020-01-01", "end_date": "2026-01-01"},
        ),
    ],
)
def test_unbounded_or_excessive_row_reports_are_controlled(
    tools: AssistantTools, name: str, period: dict
) -> None:
    result = tools.execute(ToolCall(name, {"period": period}))
    assert result.response["code"] == "invalid_financial_period"
