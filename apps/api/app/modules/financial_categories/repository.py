from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_categories.schemas import (
    FinancialCategoryCreate,
    FinancialCategoryUpdate,
)
from app.modules.financial_entries.models import FinancialEntry


class FinancialCategoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, data: FinancialCategoryCreate, *, business_id: UUID
    ) -> FinancialCategory:
        category = FinancialCategory(**data.model_dump(), business_id=business_id)
        self.session.add(category)
        self.session.flush()
        return category

    def get_by_id(
        self, category_id: UUID, *, business_id: UUID
    ) -> FinancialCategory | None:
        return self.session.scalar(
            select(FinancialCategory).where(
                FinancialCategory.id == category_id,
                FinancialCategory.business_id == business_id,
            )
        )

    def get_by_name(
        self, name: str, category_type: FinancialType, *, business_id: UUID
    ) -> FinancialCategory | None:
        return self.session.scalar(
            select(FinancialCategory).where(
                FinancialCategory.business_id == business_id,
                func.lower(FinancialCategory.name) == func.lower(name),
                FinancialCategory.type == category_type,
            )
        )

    def list(
        self,
        *,
        business_id: UUID,
        category_type: FinancialType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[FinancialCategory]:
        statement = select(FinancialCategory).where(
            FinancialCategory.business_id == business_id
        )
        if category_type is not None:
            statement = statement.where(FinancialCategory.type == category_type)
        return list(
            self.session.scalars(
                statement.order_by(FinancialCategory.name, FinancialCategory.id)
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def update(
        self, category: FinancialCategory, data: FinancialCategoryUpdate
    ) -> FinancialCategory:
        for field_name, field_value in data.model_dump(exclude_unset=True).items():
            setattr(category, field_name, field_value)
        self.session.flush()
        return category

    def has_entries(self, category_id: UUID, *, business_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(FinancialEntry.id)
                .where(
                    FinancialEntry.category_id == category_id,
                    FinancialEntry.business_id == business_id,
                )
                .limit(1)
            )
            is not None
        )

    def delete(self, category: FinancialCategory) -> None:
        self.session.delete(category)
        self.session.flush()
