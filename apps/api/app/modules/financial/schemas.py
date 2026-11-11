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
