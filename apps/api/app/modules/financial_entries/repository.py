from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.financial_categories.models import FinancialType
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.schemas import (
    FinancialEntryCreate,
    FinancialEntryUpdate,
)


class FinancialEntryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, data: FinancialEntryCreate, *, business_id: UUID
    ) -> FinancialEntry:
        entry = FinancialEntry(**data.model_dump(), business_id=business_id)
        self.session.add(entry)
        self.session.flush()
        return entry

    def get_by_id(
        self, entry_id: UUID, *, business_id: UUID, lock: bool = False
    ) -> FinancialEntry | None:
        statement = select(FinancialEntry).where(
            FinancialEntry.id == entry_id,
            FinancialEntry.business_id == business_id,
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement.execution_options(populate_existing=True))

    def list(
        self,
        *,
        business_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        entry_type: FinancialType | None = None,
        category_id: UUID | None = None,
        status: FinancialEntryStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[FinancialEntry]:
        statement = select(FinancialEntry).where(
            FinancialEntry.business_id == business_id
        )
        if start_date is not None:
            statement = statement.where(FinancialEntry.due_date >= start_date)
        if end_date is not None:
            statement = statement.where(FinancialEntry.due_date <= end_date)
        if entry_type is not None:
            statement = statement.where(FinancialEntry.type == entry_type)
        if category_id is not None:
            statement = statement.where(FinancialEntry.category_id == category_id)
        if status is not None:
            statement = statement.where(FinancialEntry.status == status)
        return list(
            self.session.scalars(
                statement.order_by(
                    FinancialEntry.due_date.desc(),
                    FinancialEntry.created_at.desc(),
                    FinancialEntry.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def update(
        self, entry: FinancialEntry, data: FinancialEntryUpdate
    ) -> FinancialEntry:
        for field_name, field_value in data.model_dump(exclude_unset=True).items():
            setattr(entry, field_name, field_value)
        self.session.flush()
        return entry

    def record_payment(
        self, entry: FinancialEntry, paid_at: datetime
    ) -> FinancialEntry:
        entry.paid_at = paid_at
        entry.status = FinancialEntryStatus.PAID
        self.session.flush()
        return entry

    def delete(self, entry: FinancialEntry) -> None:
        self.session.delete(entry)
        self.session.flush()
