from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.business_categories.models import BusinessCategory
from app.modules.business_categories.schemas import BusinessCategoryResponse
from app.modules.business_categories.service import BusinessCategoryService

# The same list for every business, read before the business exists: no authentication.
router = APIRouter(prefix="/business-categories", tags=["Business categories"])


def get_business_category_service(
    session: Annotated[Session, Depends(get_db)],
) -> BusinessCategoryService:
    return BusinessCategoryService(session)


@router.get("", response_model=list[BusinessCategoryResponse])
def list_business_categories(
    service: Annotated[BusinessCategoryService, Depends(get_business_category_service)],
) -> list[BusinessCategory]:
    return service.list()
