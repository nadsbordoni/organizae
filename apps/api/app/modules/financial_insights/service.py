from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.financial.exceptions import (
    FinancialInsightsUnavailableError,
    InvalidFinancialReportError,
)
from app.modules.financial.service import FinancialReportService
from app.modules.financial_insights.guidance import default_guidance
from app.modules.financial_insights.schemas import (
    FinancialInsight,
    FinancialInsightsResponse,
    InsightPeriod,
    InsightSeverity,
    InsightType,
    InsightValues,
)


def money(value: Decimal) -> str:
    return "R$ " + format(value, ",.2f").replace(",", "_").replace(".", ",").replace(
        "_", "."
    )


def resolve_periods(
    month: date | None, today: date
) -> tuple[InsightPeriod, InsightPeriod, bool]:
    start = month or today.replace(day=1)
    if start.day != 1 or start > today:
        raise InvalidFinancialReportError(
            "Use the first day of the current or a previous month"
        )
    last = start.replace(day=monthrange(start.year, start.month)[1])
    end = min(today, last)
    partial = end < last
    try:
        previous_last = start - timedelta(days=1)
    except OverflowError:
        raise InvalidFinancialReportError(
            "Selected month has no representable previous month"
        ) from None
    previous_end = (
        previous_last.replace(day=min(end.day, previous_last.day))
        if partial
        else previous_last
    )
    return (
        InsightPeriod(start_date=start, end_date=end),
        InsightPeriod(start_date=previous_last.replace(day=1), end_date=previous_end),
        partial,
    )


class FinancialInsightsService:
    def __init__(self, session: Session, tz: ZoneInfo) -> None:
        self.session = session
        self.tz = tz
        self.reports = FinancialReportService(session, tz)

    def analyze(
        self,
        *,
        business_id: UUID,
        month: date | None = None,
        now: datetime | None = None,
    ) -> FinancialInsightsResponse:
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise InvalidFinancialReportError("Reference clock must include a timezone")
        today = now.astimezone(self.tz).date()
        period, previous, partial = resolve_periods(month, today)
        try:
            report = self.reports.profitability(
                business_id=business_id,
                start_date=period.start_date,
                end_date=period.end_date,
                comparison_period=(previous.start_date, previous.end_date),
            )
            overdue = self.reports.overdue_expenses(
                business_id=business_id, reference_date=today
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise FinancialInsightsUnavailableError() from exc
        current, old = report.current_period, report.previous_period
        insights = []

        def add(
            kind: InsightType,
            title: str,
            description: str,
            values: InsightValues,
            *,
            comparison: InsightPeriod | None = None,
            variation: Decimal | None = None,
            analyzed: InsightPeriod = period,
            severity: InsightSeverity = InsightSeverity.WARNING,
        ) -> None:
            explanation, actions = default_guidance(kind)
            insights.append(
                FinancialInsight(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"organizae:financial-insight:v1:{business_id}:{kind.value}:{analyzed.start_date}:{analyzed.end_date}",
                    ),
                    type=kind,
                    title=title,
                    description=description,
                    period=analyzed,
                    comparison_period=comparison,
                    values=values,
                    variation_percentage=variation,
                    severity=severity,
                    reference_date=today,
                    explanation=explanation,
                    suggested_actions=actions,
                )
            )

        # Thresholds use unrounded amounts; percentages retain the financial Service's rounding.
        # Without a recorded receipt in both windows, missing data is not evidence of a drop.
        if 0 < current.paid_income < old.paid_income * Decimal("0.80"):
            add(
                InsightType.REVENUE_DROP,
                "Queda de receitas recebidas",
                f"A receita recebida foi {money(current.paid_income)}, contra {money(old.paid_income)} no período de comparação. A redução supera 20%.",
                InsightValues(
                    paid_income=current.paid_income,
                    previous_paid_income=old.paid_income,
                ),
                comparison=previous,
                variation=report.comparison.paid_income_change_percentage,
            )
        if (
            old.paid_expenses > 0
            and current.paid_expenses > old.paid_expenses * Decimal("1.20")
        ):
            add(
                InsightType.EXPENSE_INCREASE,
                "Aumento de despesas pagas",
                f"As despesas pagas foram {money(current.paid_expenses)}, contra {money(old.paid_expenses)} no período de comparação. O aumento supera 20%.",
                InsightValues(
                    paid_expenses=current.paid_expenses,
                    previous_paid_expenses=old.paid_expenses,
                ),
                comparison=previous,
                variation=report.comparison.paid_expenses_change_percentage,
            )
        if current.financial_result < 0:
            add(
                InsightType.NEGATIVE_RESULT,
                "Resultado financeiro negativo",
                f"O resultado realizado foi {money(current.financial_result)}: {money(current.paid_income)} recebidos e {money(current.paid_expenses)} pagos.",
                InsightValues(
                    paid_income=current.paid_income,
                    paid_expenses=current.paid_expenses,
                    financial_result=current.financial_result,
                ),
                severity=InsightSeverity.CRITICAL,
            )
        if overdue.entry_count:
            assert overdue.oldest_due_date is not None
            add(
                InsightType.OVERDUE_EXPENSES,
                "Despesas vencidas",
                f"Há {overdue.entry_count} despesa(s) pendente(s), totalizando {money(overdue.pending_amount)}, com vencimento anterior a {today:%d/%m/%Y}. A busca abrange todas as datas.",
                InsightValues(
                    overdue_amount=overdue.pending_amount,
                    overdue_count=overdue.entry_count,
                ),
                analyzed=InsightPeriod(
                    start_date=overdue.oldest_due_date,
                    end_date=today - timedelta(days=1),
                ),
            )
        return FinancialInsightsResponse(
            reference_date=today,
            timezone=self.tz.key,
            period=period,
            comparison_period=previous,
            is_partial=partial,
            insights=insights,
        )
