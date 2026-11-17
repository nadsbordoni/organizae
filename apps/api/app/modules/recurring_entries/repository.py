from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.financial_categories.models import FinancialType
from app.modules.financial_entries.models import FinancialEntry
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.recurring_entries.schemas import (
    RecurringEntryCreate,
    RecurringEntryUpdate,
)


class RecurringEntryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, data: RecurringEntryCreate, *, business_id: UUID
    ) -> RecurringEntry:
        entry = RecurringEntry(**data.model_dump(), business_id=business_id)
        self.session.add(entry)
        self.session.flush()
        return entry

    def get_by_id(
        self, recurring_entry_id: UUID, *, business_id: UUID, lock: bool = False
    ) -> RecurringEntry | None:
        statement = select(RecurringEntry).where(
            RecurringEntry.id == recurring_entry_id,
            RecurringEntry.business_id == business_id,
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement.execution_options(populate_existing=True))

    def list(
        self,
        *,
        business_id: UUID,
        is_active: bool | None = None,
        entry_type: FinancialType | None = None,
        category_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RecurringEntry]:
        statement = select(RecurringEntry).where(
            RecurringEntry.business_id == business_id
        )
        if is_active is not None:
            statement = statement.where(RecurringEntry.is_active == is_active)
        if entry_type is not None:
            statement = statement.where(RecurringEntry.type == entry_type)
        if category_id is not None:
            statement = statement.where(RecurringEntry.category_id == category_id)
        return list(
            self.session.scalars(
                statement.order_by(RecurringEntry.description, RecurringEntry.id)
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def update(
        self, entry: RecurringEntry, data: RecurringEntryUpdate
    ) -> RecurringEntry:
        for field_name, field_value in data.model_dump(exclude_unset=True).items():
            setattr(entry, field_name, field_value)
        self.session.flush()
        return entry

    def generated_competences(
        self,
        recurring_entry_id: UUID,
        *,
        business_id: UUID,
        start_month: date,
        end_month: date,
    ) -> set[date]:
        return set(
            self.session.scalars(
                select(FinancialEntry.competence).where(
                    FinancialEntry.recurring_entry_id == recurring_entry_id,
                    FinancialEntry.business_id == business_id,
                    FinancialEntry.competence >= start_month,
                    FinancialEntry.competence <= end_month,
                )
            ).all()
        )
