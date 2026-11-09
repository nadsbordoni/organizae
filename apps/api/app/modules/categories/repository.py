from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.categories.models import Category
from app.modules.categories.schemas import CategoryCreate, CategoryUpdate
from app.modules.services.models import Service


class CategoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, category_data: CategoryCreate, *, business_id: UUID) -> Category:
        category = Category(**category_data.model_dump(), business_id=business_id)
        self.session.add(category)
        self.session.flush()
        return category

    def get_by_id(self, category_id: UUID, *, business_id: UUID) -> Category | None:
        return self.session.scalar(
            select(Category).where(
                Category.id == category_id,
                Category.business_id == business_id,
            )
        )

    def get_by_name(self, name: str, *, business_id: UUID) -> Category | None:
        return self.session.scalar(
            select(Category).where(
                Category.business_id == business_id,
                func.lower(Category.name) == func.lower(name),
            )
        )

    def list(
        self, *, business_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[Category]:
        statement = (
            select(Category)
            .where(Category.business_id == business_id)
            .order_by(Category.name, Category.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def update(self, category: Category, category_data: CategoryUpdate) -> Category:
        for field_name, field_value in category_data.model_dump(
            exclude_unset=True
        ).items():
            setattr(category, field_name, field_value)
        self.session.flush()
        return category

    def has_services(self, category_id: UUID, *, business_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(Service.id)
                .where(
                    Service.category_id == category_id,
                    Service.business_id == business_id,
                )
                .limit(1)
            )
            is not None
        )

    def delete(self, category: Category) -> None:
        self.session.delete(category)
        self.session.flush()
