from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class InsightType(str, Enum):
    REVENUE_DROP = "REVENUE_DROP"
    EXPENSE_INCREASE = "EXPENSE_INCREASE"
    NEGATIVE_RESULT = "NEGATIVE_RESULT"
    OVERDUE_EXPENSES = "OVERDUE_EXPENSES"


class InsightSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class InsightPeriod(BaseModel):
    start_date: date
    end_date: date


class InsightValues(BaseModel):
    paid_income: Decimal | None = None
    previous_paid_income: Decimal | None = None
    paid_expenses: Decimal | None = None
    previous_paid_expenses: Decimal | None = None
    financial_result: Decimal | None = None
    overdue_amount: Decimal | None = None
    overdue_count: int | None = None


class FinancialInsight(BaseModel):
    id: UUID
    type: InsightType
    title: str
    description: str
    period: InsightPeriod
    comparison_period: InsightPeriod | None = None
    values: InsightValues
    variation_percentage: Decimal | None = None
    severity: InsightSeverity
    reference_date: date
    explanation: str
    suggested_actions: list[str]
    explanation_source: Literal["deterministic", "gemini"] = "deterministic"


class FinancialInsightsResponse(BaseModel):
    reference_date: date
    timezone: str
    period: InsightPeriod
    comparison_period: InsightPeriod
    is_partial: bool
    insights: list[FinancialInsight]


class FinancialInsightsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: date | None = None
    explain: bool = True

    @field_validator("month")
    @classmethod
    def validate_month(cls, value: date | None) -> date | None:
        if value is not None and value.day != 1:
            raise ValueError("month must be the first day of a month")
        return value
