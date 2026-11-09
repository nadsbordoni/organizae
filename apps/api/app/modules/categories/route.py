from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_business_id
from app.modules.categories.exceptions import (
    CategoryConflictError,
    CategoryError,
    CategoryNotFoundError,
    InvalidCategoryPaginationError,
)
from app.modules.categories.models import Category
from app.modules.categories.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)
from app.modules.categories.service import CategoryService

router = APIRouter(prefix="/categories", tags=["Categories"])


def get_category_service(
    session: Annotated[Session, Depends(get_db)],
) -> CategoryService:
    return CategoryService(session)


async def category_error_handler(request: Request, exc: CategoryError) -> JSONResponse:
    status_codes = {
        CategoryNotFoundError: status.HTTP_404_NOT_FOUND,
        CategoryConflictError: status.HTTP_409_CONFLICT,
        InvalidCategoryPaginationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    status_code = next(
        (
            code
            for error_type, code in status_codes.items()
            if isinstance(exc, error_type)
        ),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    detail = str(exc) if status_code != 500 else "Internal server error"
    return JSONResponse(status_code=status_code, content={"detail": detail})


CurrentBusinessId = Annotated[UUID, Depends(get_current_business_id)]
CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    category_data: CategoryCreate,
    business_id: CurrentBusinessId,
    service: CategoryServiceDep,
) -> Category:
    return service.create(category_data, business_id=business_id)


@router.get("", response_model=list[CategoryResponse])
def list_categories(
    business_id: CurrentBusinessId,
    service: CategoryServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[Category]:
    return service.list(business_id=business_id, offset=offset, limit=limit)


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(
    category_id: UUID4, business_id: CurrentBusinessId, service: CategoryServiceDep
) -> Category:
    return service.get_by_id(category_id, business_id=business_id)


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: UUID4,
    category_data: CategoryUpdate,
    business_id: CurrentBusinessId,
    service: CategoryServiceDep,
) -> Category:
    return service.update(category_id, category_data, business_id=business_id)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: UUID4, business_id: CurrentBusinessId, service: CategoryServiceDep
) -> Response:
    service.delete(category_id, business_id=business_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
