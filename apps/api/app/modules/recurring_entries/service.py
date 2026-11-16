from calendar import monthrange
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.financial_categories.models import FinancialType
from app.modules.financial_categories.repository import FinancialCategoryRepository
from app.modules.financial_entries.repository import FinancialEntryRepository
from app.modules.financial_entries.schemas import FinancialEntryCreate
from app.modules.recurring_entries.exceptions import (
    InvalidRecurringEntryError,
    RecurringEntryConflictError,
    RecurringEntryNotFoundError,
)
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.recurring_entries.repository import RecurringEntryRepository
from app.modules.recurring_entries.schemas import (
    RecurringEntryCreate,
    RecurringEntryGenerate,
    RecurringEntryGenerationResponse,
    RecurringEntryUpdate,
)


class RecurringEntryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = RecurringEntryRepository(session)
        self.category_repository = FinancialCategoryRepository(session)
        self.entry_repository = FinancialEntryRepository(session)
        self.business_repository = BusinessRepository(session)

    def get_by_id(
        self, recurring_entry_id: UUID, *, business_id: UUID, lock: bool = False
    ) -> RecurringEntry:
        entry = self.repository.get_by_id(
            recurring_entry_id, business_id=business_id, lock=lock
        )
        if entry is None:
            raise RecurringEntryNotFoundError("Recurring entry not found")
        return entry

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
        if offset < 0 or not 1 <= limit <= 100:
            raise InvalidRecurringEntryError("Invalid recurring entry pagination")
        return self.repository.list(
            business_id=business_id,
            is_active=is_active,
            entry_type=entry_type,
            category_id=category_id,
            offset=offset,
            limit=limit,
        )

    def create(
        self, data: RecurringEntryCreate, *, business_id: UUID
    ) -> RecurringEntry:
        with self._transaction():
            if self.business_repository.get_by_id(business_id) is None:
                raise BusinessNotFoundError("Business not found")
            self._validate_category(
                data.category_id, data.type, business_id=business_id
            )
            entry = self.repository.create(data, business_id=business_id)
            self.session.commit()
            self.session.refresh(entry)
        return entry

    def update(
        self, recurring_entry_id: UUID, data: RecurringEntryUpdate, *, business_id: UUID
    ) -> RecurringEntry:
        with self._transaction():
            entry = self.get_by_id(
                recurring_entry_id, business_id=business_id, lock=True
            )
            start_date = (
                data.start_date if data.start_date is not None else entry.start_date
            )
            end_date = (
                data.end_date if "end_date" in data.model_fields_set else entry.end_date
            )
            if end_date is not None and end_date < start_date:
                raise InvalidRecurringEntryError("End date must not precede start date")
            self._validate_category(
                data.category_id if data.category_id is not None else entry.category_id,
                data.type if data.type is not None else entry.type,
                business_id=business_id,
            )
            entry = self.repository.update(entry, data)
            self.session.commit()
            self.session.refresh(entry)
        return entry

    def delete(self, recurring_entry_id: UUID, *, business_id: UUID) -> None:
        with self._transaction():
            entry = self.get_by_id(
                recurring_entry_id, business_id=business_id, lock=True
            )
            self.repository.update(entry, RecurringEntryUpdate(is_active=False))
            self.session.commit()

    def generate(
        self,
        recurring_entry_id: UUID,
        data: RecurringEntryGenerate,
        *,
        business_id: UUID,
    ) -> RecurringEntryGenerationResponse:
        with self._transaction():
            entry = self.get_by_id(
                recurring_entry_id, business_id=business_id, lock=True
            )
            if not entry.is_active:
                raise RecurringEntryConflictError(
                    "Inactive recurrences cannot generate entries"
                )
            self._validate_category(
                entry.category_id, entry.type, business_id=business_id
            )
            existing = self.repository.generated_competences(
                entry.id,
                business_id=business_id,
                start_month=data.start_month,
                end_month=data.end_month,
            )
            created, skipped = [], []
            start_index = data.start_month.year * 12 + data.start_month.month - 1
            end_index = data.end_month.year * 12 + data.end_month.month - 1
            for month_index in range(start_index, end_index + 1):
                year, month_zero = divmod(month_index, 12)
                month = month_zero + 1
                competence = date(year, month, 1)
                due_date = date(
                    year, month, min(entry.due_day, monthrange(year, month)[1])
                )
                if due_date < entry.start_date or (
                    entry.end_date is not None and due_date > entry.end_date
                ):
                    continue
                if competence in existing:
                    skipped.append(competence)
                    continue
                created.append(
                    self.entry_repository.create(
                        FinancialEntryCreate(
                            category_id=entry.category_id,
                            type=entry.type,
                            description=entry.description,
                            amount=entry.amount,
                            due_date=due_date,
                        ),
                        business_id=business_id,
                        recurring_entry_id=entry.id,
                        competence=competence,
                    )
                )
            # Materialize the bounded response before commit; a serialization failure rolls back the batch.
            result = RecurringEntryGenerationResponse(
                created_entries=created, skipped_competences=skipped
            )
            self.session.commit()
        return result

    def _validate_category(
        self, category_id: UUID, entry_type: FinancialType, *, business_id: UUID
    ) -> None:
        category = self.category_repository.get_by_id(
            category_id, business_id=business_id
        )
        if category is None:
            raise InvalidRecurringEntryError(
                "Financial category not found in this business"
            )
        if category.type != entry_type:
            raise InvalidRecurringEntryError(
                "Recurrence type must match the financial category type"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            raise RecurringEntryConflictError(
                "Operation conflicts with financial records or related data"
            ) from exc
        except Exception:
            self.session.rollback()
            raise
