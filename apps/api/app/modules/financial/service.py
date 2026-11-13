from calendar import monthrange
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.modules.financial.exceptions import InvalidFinancialReportError
from app.modules.financial.repository import FinancialReportRepository
from app.modules.financial.schemas import (
    CashFlowGrouping,
    CashFlowItem,
    CashFlowResponse,
    CategoryReportItem,
    CategoryReportResponse,
    FinancialSummaryResponse,
    ProfitabilityComparison,
    ProfitabilityMetrics,
    ProfitabilityMonth,
    ProfitabilityPeriod,
    ProfitabilityResponse,
)
from app.modules.financial_categories.models import FinancialType


class FinancialReportService:
    def __init__(self, session: Session, tz: ZoneInfo) -> None:
        self.repository = FinancialReportRepository(session, tz)

    def summary(
        self,
        *,
        business_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        category_id: UUID | None = None,
    ) -> FinancialSummaryResponse:
        self._validate_period(start_date, end_date)
        paid_income, paid_expenses, pending_income, pending_expenses = (
            self.repository.summary(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                category_id=category_id,
            )
        )
        return FinancialSummaryResponse(
            paid_income=paid_income,
            paid_expenses=paid_expenses,
            balance=paid_income - paid_expenses,
            pending_income=pending_income,
            pending_expenses=pending_expenses,
        )

    def cash_flow(
        self,
        *,
        business_id: UUID,
        group_by: CashFlowGrouping = CashFlowGrouping.DAY,
        start_date: date | None = None,
        end_date: date | None = None,
        category_id: UUID | None = None,
    ) -> CashFlowResponse:
        self._validate_period(start_date, end_date)
        if group_by not in (CashFlowGrouping.DAY, CashFlowGrouping.MONTH):
            raise InvalidFinancialReportError("Cash flow grouping must be day or month")
        rows = self.repository.cash_flow(
            business_id=business_id,
            group_by=group_by,
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
        )
        items = [
            CashFlowItem(
                period=period,
                income=income,
                expenses=expenses,
                balance=income - expenses,
            )
            for period, income, expenses in rows
        ]
        income = sum((item.income for item in items), Decimal("0.00"))
        expenses = sum((item.expenses for item in items), Decimal("0.00"))
        return CashFlowResponse(
            group_by=group_by,
            items=items,
            total_income=income,
            total_expenses=expenses,
            balance=income - expenses,
        )

    def categories(
        self,
        *,
        business_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        category_id: UUID | None = None,
        entry_type: FinancialType | None = None,
    ) -> CategoryReportResponse:
        self._validate_period(start_date, end_date)
        rows = self.repository.categories(
            business_id=business_id,
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
            entry_type=entry_type,
        )
        totals = {
            movement_type: (
                sum(
                    (
                        paid
                        for _, _, row_type, paid, _ in rows
                        if row_type == movement_type
                    ),
                    Decimal("0.00"),
                ),
                sum(
                    (
                        pending
                        for _, _, row_type, _, pending in rows
                        if row_type == movement_type
                    ),
                    Decimal("0.00"),
                ),
            )
            for movement_type in FinancialType
        }
        items = [
            CategoryReportItem(
                category_id=identifier,
                category_name=name,
                type=movement_type,
                paid_total=paid,
                pending_total=pending,
                paid_percentage=self._percentage(paid, totals[movement_type][0]),
                pending_percentage=self._percentage(pending, totals[movement_type][1]),
            )
            for identifier, name, movement_type, paid, pending in rows
        ]
        return CategoryReportResponse(
            paid_income=totals[FinancialType.INCOME][0],
            paid_expenses=totals[FinancialType.EXPENSE][0],
            pending_income=totals[FinancialType.INCOME][1],
            pending_expenses=totals[FinancialType.EXPENSE][1],
            items=items,
        )

    def profitability(
        self,
        *,
        business_id: UUID,
        start_date: date,
        end_date: date,
    ) -> ProfitabilityResponse:
        self._validate_period(start_date, end_date)
        previous_start, previous_end = self._previous_period(start_date, end_date)
        current_cash = self.cash_flow(
            business_id=business_id,
            group_by=CashFlowGrouping.MONTH,
            start_date=start_date,
            end_date=end_date,
        )
        previous_cash = self.cash_flow(
            business_id=business_id,
            group_by=CashFlowGrouping.MONTH,
            start_date=previous_start,
            end_date=previous_end,
        )
        current = ProfitabilityPeriod(
            **self._profitability_metrics(
                current_cash.total_income,
                current_cash.total_expenses,
                current_cash.balance,
            ).model_dump(),
            start_date=start_date,
            end_date=end_date,
        )
        previous = ProfitabilityPeriod(
            **self._profitability_metrics(
                previous_cash.total_income,
                previous_cash.total_expenses,
                previous_cash.balance,
            ).model_dump(),
            start_date=previous_start,
            end_date=previous_end,
        )
        by_month = {item.period: item for item in current_cash.items}
        evolution = []
        start_index = start_date.year * 12 + start_date.month - 1
        end_index = end_date.year * 12 + end_date.month - 1
        for month_index in range(start_index, end_index + 1):
            year, month_zero = divmod(month_index, 12)
            period = date(year, month_zero + 1, 1)
            item = by_month.get(period)
            metrics = self._profitability_metrics(
                item.income if item else Decimal("0.00"),
                item.expenses if item else Decimal("0.00"),
                item.balance if item else Decimal("0.00"),
            )
            evolution.append(ProfitabilityMonth(period=period, **metrics.model_dump()))
        comparison = ProfitabilityComparison(
            paid_income_change=current.paid_income - previous.paid_income,
            paid_income_change_percentage=self._change_percentage(
                current.paid_income, previous.paid_income
            ),
            paid_expenses_change=current.paid_expenses - previous.paid_expenses,
            paid_expenses_change_percentage=self._change_percentage(
                current.paid_expenses, previous.paid_expenses
            ),
            financial_result_change=current.financial_result
            - previous.financial_result,
            financial_result_change_percentage=self._change_percentage(
                current.financial_result, previous.financial_result
            ),
            financial_margin_change_percentage_points=(
                current.financial_margin_percentage
                - previous.financial_margin_percentage
                if current.financial_margin_percentage is not None
                and previous.financial_margin_percentage is not None
                else None
            ),
        )
        return ProfitabilityResponse(
            current_period=current,
            previous_period=previous,
            comparison=comparison,
            monthly_evolution=evolution,
        )

    @staticmethod
    def _previous_period(start_date: date, end_date: date) -> tuple[date, date]:
        try:
            previous_end = start_date - timedelta(days=1)
            if (
                start_date.day == 1
                and end_date.day == monthrange(end_date.year, end_date.month)[1]
            ):
                months = (
                    (end_date.year - start_date.year) * 12
                    + end_date.month
                    - start_date.month
                    + 1
                )
                month_index = (start_date.year - 1) * 12 + start_date.month - 1 - months
                if month_index < 0:
                    raise OverflowError
                year_zero, month_zero = divmod(month_index, 12)
                previous_start = date(year_zero + 1, month_zero + 1, 1)
            else:
                previous_start = start_date - timedelta(
                    days=(end_date - start_date).days + 1
                )
        except OverflowError:
            raise InvalidFinancialReportError(
                "Selected period has no representable previous equivalent period"
            ) from None
        return previous_start, previous_end

    def _profitability_metrics(
        self,
        income: Decimal,
        expenses: Decimal,
        result: Decimal,
    ) -> ProfitabilityMetrics:
        return ProfitabilityMetrics(
            paid_income=income,
            paid_expenses=expenses,
            financial_result=result,
            financial_margin_percentage=self._percentage(result, income)
            if income != 0
            else None,
        )

    def _change_percentage(self, current: Decimal, previous: Decimal) -> Decimal | None:
        if previous == 0:
            return None
        return self._percentage(current - previous, abs(previous))

    @staticmethod
    def _validate_period(start_date: date | None, end_date: date | None) -> None:
        if start_date is not None and end_date is not None and end_date < start_date:
            raise InvalidFinancialReportError("End date must not precede start date")

    @staticmethod
    def _percentage(amount: Decimal, total: Decimal) -> Decimal:
        if total == 0:
            return Decimal("0.00")
        return (amount * Decimal(100) / total).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
