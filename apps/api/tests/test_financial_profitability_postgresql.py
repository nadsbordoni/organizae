from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session
from test_appointment_concurrency import postgres_agenda
from test_financial_reports_postgresql import report_agenda

from app.modules.financial.service import FinancialReportService

__all__ = ["postgres_agenda", "report_agenda"]


def test_postgresql_profitability_respects_local_payment_dates_and_company_scope(
    report_agenda,
):
    engine, business_id, *_ = report_agenda
    with Session(engine) as session:
        session.execute(text("SET TIME ZONE 'Asia/Tokyo'"))
        service = FinancialReportService(session, ZoneInfo("America/Sao_Paulo"))
        result = service.profitability(
            business_id=business_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        assert result.current_period.paid_income == Decimal("0.30")
        assert result.current_period.paid_expenses == Decimal("0.20")
        assert result.current_period.financial_result == Decimal("0.10")
        assert result.current_period.financial_margin_percentage == Decimal("33.33")
        assert result.previous_period.paid_income == Decimal("0.00")
        assert result.previous_period.financial_margin_percentage is None
        assert result.monthly_evolution[0].financial_margin_percentage == Decimal(
            "33.33"
        )
        assert result.comparison.paid_income_change_percentage is None


def test_postgresql_profitability_monthly_comparison_and_percentage_points(
    report_agenda,
):
    engine, business_id, *_ = report_agenda
    with Session(engine) as session:
        result = FinancialReportService(
            session, ZoneInfo("America/Sao_Paulo")
        ).profitability(
            business_id=business_id,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )
        assert result.previous_period.start_date == date(2026, 1, 1)
        assert result.previous_period.end_date == date(2026, 1, 31)
        assert result.current_period.paid_income == Decimal("100.00")
        assert result.previous_period.paid_income == Decimal("0.30")
        assert result.comparison.paid_income_change_percentage == Decimal("33233.33")
        assert result.comparison.financial_result_change_percentage == Decimal(
            "99900.00"
        )
        assert result.comparison.financial_margin_change_percentage_points == Decimal(
            "66.67"
        )
        assert result.monthly_evolution[0].period == date(2026, 2, 1)
