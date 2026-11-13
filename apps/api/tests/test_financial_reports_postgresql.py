import os
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_appointment_concurrency import postgres_agenda

with patch.dict(
    os.environ,
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    import app.db.session  # noqa: F401

from app.modules.businesses.models import Business, ServiceMode
from app.modules.financial.schemas import CashFlowGrouping
from app.modules.financial.service import FinancialReportService
from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.schemas import FinancialEntryPayment
from app.modules.financial_entries.service import FinancialEntryService
from app.modules.recurring_entries.schemas import (
    RecurringEntryCreate,
    RecurringEntryGenerate,
)
from app.modules.recurring_entries.service import RecurringEntryService

__all__ = ["postgres_agenda"]


@pytest.fixture
def report_agenda(postgres_agenda):
    engine, business_id, *_ = postgres_agenda
    foreign_id, income_id, expense_id, foreign_category_id = (uuid4() for _ in range(4))
    with Session(engine) as session:
        session.add(
            Business(
                id=foreign_id,
                name="Foreign",
                category_id=1,
                whatsapp="85999999999",
                service_mode=ServiceMode.PRESENCIAL,
            )
        )
        session.flush()
        session.add_all(
            [
                FinancialCategory(
                    id=income_id,
                    business_id=business_id,
                    name="Sales",
                    type=FinancialType.INCOME,
                ),
                FinancialCategory(
                    id=expense_id,
                    business_id=business_id,
                    name="Costs",
                    type=FinancialType.EXPENSE,
                ),
                FinancialCategory(
                    id=foreign_category_id,
                    business_id=foreign_id,
                    name="Foreign",
                    type=FinancialType.INCOME,
                ),
            ]
        )
        session.flush()
        for amount, category_id, movement_type, paid_at, due_date, status, owner_id in [
            (
                "0.10",
                income_id,
                "INCOME",
                "2026-01-31T23:30:00-03:00",
                "2025-12-01",
                "PAID",
                business_id,
            ),
            (
                "0.20",
                income_id,
                "INCOME",
                "2026-01-31T23:31:00-03:00",
                "2025-12-01",
                "PAID",
                business_id,
            ),
            (
                "0.20",
                expense_id,
                "EXPENSE",
                "2026-01-31T23:32:00-03:00",
                "2025-12-01",
                "PAID",
                business_id,
            ),
            (
                "100",
                income_id,
                "INCOME",
                "2026-02-01T00:00:00-03:00",
                "2026-01-31",
                "PAID",
                business_id,
            ),
            ("0.05", income_id, "INCOME", None, "2026-01-31", "PENDING", business_id),
            ("0.07", expense_id, "EXPENSE", None, "2026-02-01", "PENDING", business_id),
            ("999", income_id, "INCOME", None, "2026-01-31", "CANCELLED", business_id),
            (
                "9999",
                foreign_category_id,
                "INCOME",
                "2026-01-31T12:00:00Z",
                "2026-01-31",
                "PAID",
                foreign_id,
            ),
        ]:
            session.add(
                FinancialEntry(
                    business_id=owner_id,
                    category_id=category_id,
                    type=movement_type,
                    description="Entry",
                    amount=Decimal(amount),
                    due_date=date.fromisoformat(due_date),
                    paid_at=datetime.fromisoformat(paid_at) if paid_at else None,
                    status=status,
                )
            )
        session.commit()
    return engine, business_id, income_id, expense_id, foreign_category_id


def test_postgresql_report_dates_are_independent_of_connection_timezone(report_agenda):
    engine, business_id, *_ = report_agenda
    with Session(engine) as session:
        session.execute(text("SET TIME ZONE 'Asia/Tokyo'"))
        service = FinancialReportService(session, ZoneInfo("America/Sao_Paulo"))
        filters = {
            "business_id": business_id,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 31),
        }
        summary = service.summary(**filters)
        assert summary.model_dump(mode="json") == {
            "paid_income": "0.30",
            "paid_expenses": "0.20",
            "balance": "0.10",
            "pending_income": "0.05",
            "pending_expenses": "0.00",
        }
        for grouping, expected_period in [
            (CashFlowGrouping.DAY, date(2026, 1, 31)),
            (CashFlowGrouping.MONTH, date(2026, 1, 1)),
        ]:
            cash = service.cash_flow(**filters, group_by=grouping)
            assert len(cash.items) == 1 and cash.items[0].period == expected_period
            assert cash.total_income == Decimal("0.30") and cash.balance == Decimal(
                "0.10"
            )
        categories = service.categories(**filters)
        assert categories.paid_income == Decimal(
            "0.30"
        ) and categories.paid_expenses == Decimal("0.20")
        assert all(
            item.paid_percentage == Decimal("100.00") for item in categories.items
        )
        utc_summary = FinancialReportService(session, ZoneInfo("UTC")).summary(
            **filters
        )
        assert utc_summary.paid_income == utc_summary.paid_expenses == Decimal("0.00")
        assert utc_summary.pending_income == Decimal("0.05")


def test_postgresql_aggregates_support_totals_above_individual_entry_limit(
    report_agenda,
):
    engine, business_id, income_id, *_ = report_agenda
    with Session(engine) as session:
        session.add_all(
            FinancialEntry(
                business_id=business_id,
                category_id=income_id,
                type="INCOME",
                description="Large amount",
                amount=Decimal("9999999999.99"),
                due_date=date(2026, 6, 1),
                paid_at=datetime(2026, 6, 15, 12, tzinfo=UTC),
                status=FinancialEntryStatus.PAID,
            )
            for _ in range(3)
        )
        session.commit()
        service = FinancialReportService(session, ZoneInfo("UTC"))
        filters = {
            "business_id": business_id,
            "start_date": date(2026, 6, 1),
            "end_date": date(2026, 6, 30),
        }
        expected = Decimal("29999999999.97")
        assert service.summary(**filters).balance == expected
        assert service.cash_flow(**filters).total_income == expected
        assert service.categories(**filters).paid_income == expected


def test_postgresql_filters_do_not_expose_foreign_categories_and_empty_totals_are_decimal(
    report_agenda,
):
    engine, business_id, _, _, foreign_category_id = report_agenda
    with Session(engine) as session:
        service = FinancialReportService(session, ZoneInfo("America/Sao_Paulo"))
        for identifier in (foreign_category_id, uuid4()):
            summary = service.summary(business_id=business_id, category_id=identifier)
            assert all(
                value == "0.00" for value in summary.model_dump(mode="json").values()
            )
            assert (
                service.categories(
                    business_id=business_id, category_id=identifier
                ).items
                == []
            )
            assert (
                service.cash_flow(business_id=business_id, category_id=identifier).items
                == []
            )


def test_postgresql_reports_include_generated_entries_without_counting_templates(
    report_agenda,
):
    engine, business_id, income_id, *_ = report_agenda
    with Session(engine) as session:
        reports = FinancialReportService(session, ZoneInfo("UTC"))
        baseline = reports.summary(business_id=business_id)
        recurrences = RecurringEntryService(session)
        recurrence = recurrences.create(
            RecurringEntryCreate(
                category_id=income_id,
                type=FinancialType.INCOME,
                description="Subscription",
                amount="10.10",
                due_day=15,
                start_date=date(2026, 1, 1),
            ),
            business_id=business_id,
        )
        assert reports.summary(business_id=business_id) == baseline
        period = RecurringEntryGenerate(
            start_month=date(2026, 1, 1), end_month=date(2026, 3, 1)
        )
        generated = recurrences.generate(recurrence.id, period, business_id=business_id)
        assert len(generated.created_entries) == 3
        assert (
            recurrences.generate(
                recurrence.id, period, business_id=business_id
            ).created_entries
            == []
        )
        FinancialEntryService(session).pay(
            generated.created_entries[0].id,
            FinancialEntryPayment(paid_at=datetime(2026, 1, 20, tzinfo=UTC)),
            business_id=business_id,
        )
        summary = reports.summary(business_id=business_id)
        assert summary.paid_income == baseline.paid_income + Decimal("10.10")
        assert summary.pending_income == baseline.pending_income + Decimal("20.20")
        assert (
            reports.cash_flow(business_id=business_id).total_income
            == summary.paid_income
        )
        assert (
            reports.categories(business_id=business_id).pending_income
            == summary.pending_income
        )
