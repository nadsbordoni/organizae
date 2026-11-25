from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.business_categories.models import BusinessCategory


class BusinessCategoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self) -> list[BusinessCategory]:
        # Seed order, which keeps "Outro" last in the sign-up list.
        statement = select(BusinessCategory).order_by(BusinessCategory.id)
        return list(self.session.scalars(statement).all())
