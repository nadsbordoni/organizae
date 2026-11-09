from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.categories.exceptions import (
    CategoryConflictError,
    CategoryNotFoundError,
    InvalidCategoryPaginationError,
)
from app.modules.categories.models import Category
from app.modules.categories.repository import CategoryRepository
from app.modules.categories.schemas import CategoryCreate, CategoryUpdate


class CategoryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = CategoryRepository(session)
        self.business_repository = BusinessRepository(session)

    def create(self, category_data: CategoryCreate, *, business_id: UUID) -> Category:
        with self._transaction():
            if self.business_repository.get_by_id(business_id) is None:
                raise BusinessNotFoundError("Business not found")
            self._ensure_unique_name(category_data.name, business_id=business_id)
            category = self.repository.create(category_data, business_id=business_id)
            self.session.commit()
            self.session.refresh(category)
        return category

    def get_by_id(self, category_id: UUID, *, business_id: UUID) -> Category:
        category = self.repository.get_by_id(category_id, business_id=business_id)
        if category is None:
            raise CategoryNotFoundError("Category not found")
        return category

    def list(
        self, *, business_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[Category]:
        if offset < 0 or not 1 <= limit <= 100:
            raise InvalidCategoryPaginationError("Invalid category pagination")
        return self.repository.list(business_id=business_id, offset=offset, limit=limit)

    def update(
        self, category_id: UUID, category_data: CategoryUpdate, *, business_id: UUID
    ) -> Category:
        with self._transaction():
            category = self.get_by_id(category_id, business_id=business_id)
            if category_data.name is not None:
                self._ensure_unique_name(
                    category_data.name, business_id=business_id, category_id=category.id
                )
            category = self.repository.update(category, category_data)
            self.session.commit()
            self.session.refresh(category)
        return category

    def delete(self, category_id: UUID, *, business_id: UUID) -> None:
        with self._transaction():
            category = self.get_by_id(category_id, business_id=business_id)
            if self.repository.has_services(category.id, business_id=business_id):
                raise CategoryConflictError(
                    "Category is linked to services; remove its associations before deleting"
                )
            self.repository.delete(category)
            self.session.commit()

    def _ensure_unique_name(
        self, name: str, *, business_id: UUID, category_id: UUID | None = None
    ) -> None:
        existing = self.repository.get_by_name(name, business_id=business_id)
        if existing is not None and existing.id != category_id:
            raise CategoryConflictError("A category with this name already exists")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            raise CategoryConflictError(
                "Operation conflicts with existing categories or related records"
            ) from exc
        except Exception:
            self.session.rollback()
            raise
