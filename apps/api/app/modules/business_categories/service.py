from sqlalchemy.orm import Session

from app.modules.business_categories.models import BusinessCategory
from app.modules.business_categories.repository import BusinessCategoryRepository


class BusinessCategoryService:
    def __init__(self, session: Session) -> None:
        self.repository = BusinessCategoryRepository(session)

    def list(self) -> list[BusinessCategory]:
        return self.repository.list()
