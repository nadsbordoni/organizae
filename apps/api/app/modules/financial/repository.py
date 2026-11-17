from datetime import date
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, case, extract, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.financial.schemas import CashFlowGrouping
from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus


class FinancialReportRepository:
    def __init__(self, session: Session, tz: ZoneInfo) -> None:
        self.session = session
        self.tz = tz

    def summary(
        self,
        *,
        business_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        category_id: UUID | None = None,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        statement = select(
            self._total(FinancialType.INCOME, FinancialEntryStatus.PAID),
            self._total(FinancialType.EXPENSE, FinancialEntryStatus.PAID),
            self._total(FinancialType.INCOME, FinancialEntryStatus.PENDING),
            self._total(FinancialType.EXPENSE, FinancialEntryStatus.PENDING),
        ).where(
            *self._filters(
                business_id=business_id,
                report_date=self._effective_date(),
                start_date=start_date,
                end_date=end_date,
                category_id=category_id,
            )
        )
        return tuple(self.session.execute(statement).one())

    def cash_flow(
        self,
        *,
        business_id: UUID,
        group_by: CashFlowGrouping,
        start_date: date | None = None,
        end_date: date | None = None,
        category_id: UUID | None = None,
    ) -> list[tuple[date, Decimal, Decimal]]:
        paid_date = self._paid_date()
        parts = [extract("year", paid_date), extract("month", paid_date)]
        if group_by == CashFlowGrouping.DAY:
            parts.append(extract("day", paid_date))
        statement = (
            select(
                *parts,
                self._total(FinancialType.INCOME, FinancialEntryStatus.PAID),
                self._total(FinancialType.EXPENSE, FinancialEntryStatus.PAID),
            )
            .where(
                FinancialEntry.status == FinancialEntryStatus.PAID,
                *self._filters(
                    business_id=business_id,
                    report_date=paid_date,
                    start_date=start_date,
                    end_date=end_date,
                    category_id=category_id,
                ),
            )
            .group_by(*parts)
            .order_by(*parts)
        )
        return [
            (
                date(
                    int(row[0]),
                    int(row[1]),
                    int(row[2]) if group_by == CashFlowGrouping.DAY else 1,
                ),
                row[-2],
                row[-1],
            )
            for row in self.session.execute(statement)
        ]

    def categories(
        self,
        *,
        business_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        category_id: UUID | None = None,
        entry_type: FinancialType | None = None,
    ) -> list[tuple[UUID, str, FinancialType, Decimal, Decimal]]:
        statement = (
            select(
                FinancialCategory.id,
                FinancialCategory.name,
                FinancialEntry.type,
                func.coalesce(
                    func.sum(
                        case(
                            (
                                FinancialEntry.status == FinancialEntryStatus.PAID,
                                FinancialEntry.amount,
                            ),
                            else_=Decimal("0.00"),
                        )
                    ),
                    Decimal("0.00"),
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                FinancialEntry.status == FinancialEntryStatus.PENDING,
                                FinancialEntry.amount,
                            ),
                            else_=Decimal("0.00"),
                        )
                    ),
                    Decimal("0.00"),
                ),
            )
            .select_from(FinancialEntry)
            .join(
                FinancialCategory,
                and_(
                    FinancialCategory.id == FinancialEntry.category_id,
                    FinancialCategory.business_id == FinancialEntry.business_id,
                    FinancialCategory.type == FinancialEntry.type,
                ),
            )
            .where(
                *self._filters(
                    business_id=business_id,
                    report_date=self._effective_date(),
                    start_date=start_date,
                    end_date=end_date,
                    category_id=category_id,
                    entry_type=entry_type,
                )
            )
            .group_by(
                FinancialCategory.id,
                FinancialCategory.name,
                FinancialEntry.type,
            )
            .order_by(FinancialEntry.type, FinancialCategory.name, FinancialCategory.id)
        )
        return [tuple(row) for row in self.session.execute(statement)]

    def overdue_expenses(
        self, *, business_id: UUID, reference_date: date
    ) -> tuple[Decimal, int, date | None]:
        statement = select(
            self._total(FinancialType.EXPENSE, FinancialEntryStatus.PENDING),
            func.count(FinancialEntry.id),
            func.min(FinancialEntry.due_date),
        ).where(
            *self._filters(
                business_id=business_id,
                report_date=FinancialEntry.due_date,
                start_date=None,
                end_date=None,
                category_id=None,
                entry_type=FinancialType.EXPENSE,
            ),
            FinancialEntry.status == FinancialEntryStatus.PENDING,
            FinancialEntry.due_date < reference_date,
        )
        return tuple(self.session.execute(statement).one())

    def _paid_date(self) -> ColumnElement[date]:
        return func.date(func.timezone(self.tz.key, FinancialEntry.paid_at), type_=Date)

    def _effective_date(self) -> ColumnElement[date]:
        return case(
            (FinancialEntry.status == FinancialEntryStatus.PAID, self._paid_date()),
            else_=FinancialEntry.due_date,
        )

    @staticmethod
    def _total(
        entry_type: FinancialType, status: FinancialEntryStatus
    ) -> ColumnElement[Decimal]:
        return func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            FinancialEntry.type == entry_type,
                            FinancialEntry.status == status,
                        ),
                        FinancialEntry.amount,
                    ),
                    else_=Decimal("0.00"),
                )
            ),
            Decimal("0.00"),
        )

    @staticmethod
    def _filters(
        *,
        business_id: UUID,
        report_date: ColumnElement[date],
        start_date: date | None,
        end_date: date | None,
        category_id: UUID | None,
        entry_type: FinancialType | None = None,
    ) -> list[ColumnElement[bool]]:
        conditions = [
            FinancialEntry.business_id == business_id,
            FinancialEntry.status.in_(
                (FinancialEntryStatus.PAID, FinancialEntryStatus.PENDING)
            ),
        ]
        if start_date is not None:
            conditions.append(report_date >= start_date)
        if end_date is not None:
            conditions.append(report_date <= end_date)
        if category_id is not None:
            conditions.append(FinancialEntry.category_id == category_id)
        if entry_type is not None:
            conditions.append(FinancialEntry.type == entry_type)
        return conditions
