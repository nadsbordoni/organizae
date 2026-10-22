from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.exceptions import (
    BusinessCategoryNotFoundError,
    BusinessConflictError,
    BusinessNotFoundError,
    InvalidBusinessPaginationError,
)
from app.modules.businesses.models import Business
from app.modules.businesses.repository import BusinessRepository
from app.modules.businesses.schemas import BusinessCreate, BusinessUpdate


class BusinessService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BusinessRepository(session)

    def get_by_id(self, business_id: int) -> Business:
        business = self.repository.get_by_id(business_id)
        if business is None:
            raise BusinessNotFoundError("Business not found")
        return business

    def list(self, *, offset: int = 0, limit: int = 100) -> list[Business]:
        if offset < 0 or limit < 1:
            raise InvalidBusinessPaginationError(
                "offset must be non-negative and limit must be positive"
            )
        return self.repository.list(offset=offset, limit=limit)

    def create(self, business_data: BusinessCreate) -> Business:
        with self._transaction():
            self._validate_category(business_data.category_id)
            business = self.repository.create(business_data)
            self.session.commit()
            self.session.refresh(business)
        return business

    def update(self, business_id: int, business_data: BusinessUpdate) -> Business:
        with self._transaction():
            business = self.get_by_id(business_id)

            if business_data.category_id is not None:
                self._validate_category(business_data.category_id)

            business = self.repository.update(business, business_data)
            self.session.commit()
            self.session.refresh(business)

        return business

    def delete(self, business_id: int) -> None:
        with self._transaction():
            if not self.repository.delete(business_id):
                raise BusinessNotFoundError("Business not found")
            self.session.commit()

    def _validate_category(self, category_id: int) -> None:
        if self.session.get(BusinessCategory, category_id) is None:
            raise BusinessCategoryNotFoundError("Business category not found")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield

        except IntegrityError as exc:
            self.session.rollback()
            raise BusinessConflictError(
                "Operation conflicts with related data or database constraints"
            ) from exc

        except Exception:
            # Cleanup must also cover unexpected errors without hiding them.
            self.session.rollback()
            raise
