from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import UUID4, BaseModel

from app.modules.financial_categories.models import FinancialType


class CashFlowGrouping(str, Enum):
    DAY = "day"
    MONTH = "month"


class FinancialTotals(BaseModel):
    paid_income: Decimal
    paid_expenses: Decimal
    pending_income: Decimal
    pending_expenses: Decimal


class FinancialSummaryResponse(FinancialTotals):
    balance: Decimal


class CashFlowItem(BaseModel):
    period: date
    income: Decimal
    expenses: Decimal
    balance: Decimal


class CashFlowResponse(BaseModel):
    group_by: CashFlowGrouping
    items: list[CashFlowItem]
    total_income: Decimal
    total_expenses: Decimal
    balance: Decimal


class CategoryReportItem(BaseModel):
    category_id: UUID4
    category_name: str
    type: FinancialType
    paid_total: Decimal
    pending_total: Decimal
    paid_percentage: Decimal
    pending_percentage: Decimal


class CategoryReportResponse(FinancialTotals):
    items: list[CategoryReportItem]


class ProfitabilityMetrics(BaseModel):
    paid_income: Decimal
    paid_expenses: Decimal
    financial_result: Decimal
    financial_margin_percentage: Decimal | None


class ProfitabilityPeriod(ProfitabilityMetrics):
    start_date: date
    end_date: date


class ProfitabilityMonth(ProfitabilityMetrics):
    period: date


class ProfitabilityComparison(BaseModel):
    paid_income_change: Decimal
    paid_income_change_percentage: Decimal | None
    paid_expenses_change: Decimal
    paid_expenses_change_percentage: Decimal | None
    financial_result_change: Decimal
    financial_result_change_percentage: Decimal | None
    financial_margin_change_percentage_points: Decimal | None


class ProfitabilityResponse(BaseModel):
    current_period: ProfitabilityPeriod
    previous_period: ProfitabilityPeriod
    comparison: ProfitabilityComparison
    monthly_evolution: list[ProfitabilityMonth]
