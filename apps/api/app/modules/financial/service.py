from datetime import date
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
