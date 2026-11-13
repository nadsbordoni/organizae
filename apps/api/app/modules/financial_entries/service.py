from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.appointments.repository import AppointmentRepository
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.financial_categories.models import FinancialType
from app.modules.financial_categories.repository import FinancialCategoryRepository
from app.modules.financial_entries.exceptions import (
    FinancialEntryConflictError,
    FinancialEntryNotFoundError,
    InvalidFinancialEntryError,
)
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.repository import FinancialEntryRepository
from app.modules.financial_entries.schemas import (
    FinancialEntryCreate,
    FinancialEntryPayment,
    FinancialEntryUpdate,
)


class FinancialEntryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = FinancialEntryRepository(session)
        self.category_repository = FinancialCategoryRepository(session)
        self.appointment_repository = AppointmentRepository(session)
        self.business_repository = BusinessRepository(session)

    def get_by_id(
        self, entry_id: UUID, *, business_id: UUID, lock: bool = False
    ) -> FinancialEntry:
        entry = self.repository.get_by_id(entry_id, business_id=business_id, lock=lock)
        if entry is None:
            raise FinancialEntryNotFoundError("Financial entry not found")
        return entry

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
        if offset < 0 or not 1 <= limit <= 100:
            raise InvalidFinancialEntryError("Invalid financial entry pagination")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise InvalidFinancialEntryError("End date must not precede start date")
        return self.repository.list(
            business_id=business_id,
            start_date=start_date,
            end_date=end_date,
            entry_type=entry_type,
            category_id=category_id,
            status=status,
            offset=offset,
            limit=limit,
        )

    def create(
        self, data: FinancialEntryCreate, *, business_id: UUID
    ) -> FinancialEntry:
        with self._transaction():
            if self.business_repository.get_by_id(business_id) is None:
                raise BusinessNotFoundError("Business not found")
            self._validate_references(
                data.category_id,
                data.type,
                data.appointment_id,
                business_id=business_id,
            )
            entry = self.repository.create(data, business_id=business_id)
            self.session.commit()
            self.session.refresh(entry)
        return entry

    def update(
        self, entry_id: UUID, data: FinancialEntryUpdate, *, business_id: UUID
    ) -> FinancialEntry:
        with self._transaction():
            entry = self.get_by_id(entry_id, business_id=business_id, lock=True)
            self._ensure_editable(entry)
            self._validate_references(
                data.category_id if data.category_id is not None else entry.category_id,
                data.type if data.type is not None else entry.type,
                data.appointment_id
                if "appointment_id" in data.model_fields_set
                else entry.appointment_id,
                business_id=business_id,
            )
            entry = self.repository.update(entry, data)
            self.session.commit()
            self.session.refresh(entry)
        return entry

    def delete(self, entry_id: UUID, *, business_id: UUID) -> None:
        with self._transaction():
            entry = self.get_by_id(entry_id, business_id=business_id, lock=True)
            self._ensure_editable(entry)
            if entry.recurring_entry_id is not None:
                raise FinancialEntryConflictError(
                    "Recurring entries must be cancelled instead of deleted to preserve competence history"
                )
            self.repository.delete(entry)
            self.session.commit()

    def pay(
        self,
        entry_id: UUID,
        data: FinancialEntryPayment,
        *,
        business_id: UUID,
        now: datetime | None = None,
    ) -> FinancialEntry:
        with self._transaction():
            entry = self.get_by_id(entry_id, business_id=business_id, lock=True)
            if entry.status != FinancialEntryStatus.PENDING:
                raise FinancialEntryConflictError("Only pending entries can be paid")
            now = now or datetime.now(UTC)
            paid_at = data.paid_at.astimezone(UTC) if data.paid_at is not None else now
            if paid_at > now:
                raise InvalidFinancialEntryError("Payment date cannot be in the future")
            entry = self.repository.record_payment(entry, paid_at)
            self.session.commit()
            self.session.refresh(entry)
        return entry

    def _validate_references(
        self,
        category_id: UUID,
        entry_type: FinancialType,
        appointment_id: UUID | None,
        *,
        business_id: UUID,
    ) -> None:
        category = self.category_repository.get_by_id(
            category_id, business_id=business_id
        )
        if category is None:
            raise InvalidFinancialEntryError(
                "Financial category not found in this business"
            )
        if category.type != entry_type:
            raise InvalidFinancialEntryError(
                "Entry type must match the financial category type"
            )
        if (
            appointment_id is not None
            and self.appointment_repository.get_by_id(
                appointment_id, business_id=business_id
            )
            is None
        ):
            raise InvalidFinancialEntryError("Appointment not found in this business")

    @staticmethod
    def _ensure_editable(entry: FinancialEntry) -> None:
        if entry.status == FinancialEntryStatus.PAID:
            raise FinancialEntryConflictError(
                "Paid entries cannot be edited or deleted"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            raise FinancialEntryConflictError(
                "Operation conflicts with financial records or related data"
            ) from exc
        except Exception:
            self.session.rollback()
            raise
