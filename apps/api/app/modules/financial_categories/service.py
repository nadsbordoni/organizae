from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.financial_categories.exceptions import (
    FinancialCategoryConflictError,
    FinancialCategoryNotFoundError,
    InvalidFinancialCategoryPaginationError,
)
from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_categories.repository import FinancialCategoryRepository
from app.modules.financial_categories.schemas import (
    FinancialCategoryCreate,
    FinancialCategoryUpdate,
)


class FinancialCategoryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = FinancialCategoryRepository(session)
        self.business_repository = BusinessRepository(session)

    def create(
        self, data: FinancialCategoryCreate, *, business_id: UUID
    ) -> FinancialCategory:
        with self._transaction():
            if self.business_repository.get_by_id(business_id) is None:
                raise BusinessNotFoundError("Business not found")
            self._ensure_unique(data.name, data.type, business_id=business_id)
            category = self.repository.create(data, business_id=business_id)
            self.session.commit()
            self.session.refresh(category)
        return category

    def get_by_id(self, category_id: UUID, *, business_id: UUID) -> FinancialCategory:
        category = self.repository.get_by_id(category_id, business_id=business_id)
        if category is None:
            raise FinancialCategoryNotFoundError("Financial category not found")
        return category

    def list(
        self,
        *,
        business_id: UUID,
        category_type: FinancialType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[FinancialCategory]:
        if offset < 0 or not 1 <= limit <= 100:
            raise InvalidFinancialCategoryPaginationError(
                "Invalid financial category pagination"
            )
        return self.repository.list(
            business_id=business_id,
            category_type=category_type,
            offset=offset,
            limit=limit,
        )

    def update(
        self, category_id: UUID, data: FinancialCategoryUpdate, *, business_id: UUID
    ) -> FinancialCategory:
        with self._transaction():
            category = self.get_by_id(category_id, business_id=business_id)
            target_type = data.type if data.type is not None else category.type
            if target_type != category.type and (
                self.repository.has_entries(category.id, business_id=business_id)
                or self.repository.has_recurring_entries(
                    category.id, business_id=business_id
                )
            ):
                raise FinancialCategoryConflictError(
                    "Cannot change the type of a category linked to entries or recurrences"
                )
            self._ensure_unique(
                data.name if data.name is not None else category.name,
                target_type,
                business_id=business_id,
                category_id=category.id,
            )
            category = self.repository.update(category, data)
            self.session.commit()
            self.session.refresh(category)
        return category

    def delete(self, category_id: UUID, *, business_id: UUID) -> None:
        with self._transaction():
            category = self.get_by_id(category_id, business_id=business_id)
            if self.repository.has_entries(
                category.id, business_id=business_id
            ) or self.repository.has_recurring_entries(
                category.id, business_id=business_id
            ):
                raise FinancialCategoryConflictError(
                    "Financial category is linked to entries or recurrences"
                )
            self.repository.delete(category)
            self.session.commit()

    def _ensure_unique(
        self,
        name: str,
        category_type: FinancialType,
        *,
        business_id: UUID,
        category_id: UUID | None = None,
    ) -> None:
        existing = self.repository.get_by_name(
            name, category_type, business_id=business_id
        )
        if existing is not None and existing.id != category_id:
            raise FinancialCategoryConflictError(
                "A financial category with this name and type already exists"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            raise FinancialCategoryConflictError(
                "Operation conflicts with financial categories or related records"
            ) from exc
        except Exception:
            self.session.rollback()
            raise
