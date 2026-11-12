from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

from app.modules.financial.schemas import CashFlowGrouping
from app.modules.financial_categories.models import FinancialType


class InvalidFinancialPeriodError(ValueError):
    pass


class FinancialPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "today",
        "yesterday",
        "this_month",
        "last_month",
        "this_year",
        "last_year",
        "last_7_days",
        "last_30_days",
        "month",
        "custom",
        "all_time",
    ] = "this_month"
    month: int | None = Field(default=None, ge=1, le=12, strict=True)
    year: int | None = Field(default=None, ge=1, le=9999, strict=True)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> "FinancialPeriod":
        if self.kind == "custom":
            if self.start_date is None or self.end_date is None:
                raise ValueError("Custom periods require both dates")
            if self.end_date < self.start_date:
                raise ValueError("End date must not precede start date")
        elif self.start_date is not None or self.end_date is not None:
            raise ValueError("Dates are only accepted for custom periods")
        if self.kind == "month":
            if self.month is None:
                raise ValueError("Month is required")
        elif self.month is not None or self.year is not None:
            raise ValueError("Month and year are only accepted for month periods")
        return self

    def resolve(
        self, tz: ZoneInfo, *, now: datetime | None = None
    ) -> tuple[date | None, date | None]:
        today = (now or datetime.now(tz)).astimezone(tz).date()
        try:
            if self.kind == "all_time":
                return None, None
            if self.kind == "custom":
                return self.start_date, self.end_date
            if self.kind == "today":
                return today, today
            if self.kind == "yesterday":
                yesterday = today - timedelta(days=1)
                return yesterday, yesterday
            if self.kind in ("last_7_days", "last_30_days"):
                days = 7 if self.kind == "last_7_days" else 30
                return today - timedelta(days=days - 1), today
            if self.kind in ("this_year", "last_year"):
                year = today.year - (self.kind == "last_year")
                return date(year, 1, 1), date(year, 12, 31)
            year, month = today.year, today.month
            if self.kind == "last_month":
                previous = today.replace(day=1) - timedelta(days=1)
                year, month = previous.year, previous.month
            elif self.kind == "month":
                assert self.month is not None
                month = self.month
                year = (
                    self.year
                    if self.year is not None
                    else today.year - (month > today.month)
                )
            return date(year, month, 1), date(year, month, monthrange(year, month)[1])
        except (OverflowError, ValueError) as exc:
            raise InvalidFinancialPeriodError(
                "Período fora do intervalo de datas suportado."
            ) from exc


class FinancialReportArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: FinancialPeriod | None = None
    category_id: UUID4 | None = None


class CashFlowArguments(FinancialReportArguments):
    group_by: CashFlowGrouping = CashFlowGrouping.DAY


class CategoryReportArguments(FinancialReportArguments):
    entry_type: FinancialType | None = None


class ProfitabilityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: FinancialPeriod | None = None


class PendingEntriesArguments(FinancialReportArguments):
    entry_type: FinancialType | None = None
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=20, ge=1, le=50, strict=True)


class FinancialCategoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_type: FinancialType | None = None
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=20, ge=1, le=50, strict=True)


FINANCIAL_TOOL_SCHEMAS: dict[str, tuple[type[BaseModel], str]] = {
    "get_financial_summary": (
        FinancialReportArguments,
        "Receitas recebidas, despesas pagas, saldo e pendências. Padrão: mês atual completo.",
    ),
    "get_cash_flow": (
        CashFlowArguments,
        "Fluxo de caixa realizado, por dia ou mês; apenas pagamentos. Padrão: mês atual.",
    ),
    "get_financial_category_report": (
        CategoryReportArguments,
        "Totais pagos/pendentes por categoria. INCOME=receitas; EXPENSE=despesas. Padrão: mês atual.",
    ),
    "list_financial_categories": (
        FinancialCategoryArguments,
        "Lista categorias financeiras e IDs reais, inclusive sem lançamentos. INCOME=receita, EXPENSE=despesa.",
    ),
    "list_pending_financial_entries": (
        PendingEntriesArguments,
        "Lista pendências por vencimento. EXPENSE=despesas; INCOME=receitas. Sem período: todas as datas.",
    ),
    "get_financial_profitability": (
        ProfitabilityArguments,
        "Resultado e margem financeira sobre valores pagos; não lucro contábil. Padrão: mês atual completo.",
    ),
}
