from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_business_id
from app.modules.financial_categories.exceptions import (
    FinancialCategoryConflictError,
    FinancialCategoryError,
    FinancialCategoryNotFoundError,
    InvalidFinancialCategoryPaginationError,
)
from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_categories.schemas import (
    FinancialCategoryCreate,
    FinancialCategoryResponse,
    FinancialCategoryUpdate,
)
from app.modules.financial_categories.service import FinancialCategoryService

router = APIRouter(prefix="/financial-categories", tags=["Financial categories"])


def get_financial_category_service(
    session: Annotated[Session, Depends(get_db)],
) -> FinancialCategoryService:
    return FinancialCategoryService(session)


async def financial_category_error_handler(
    request: Request, exc: FinancialCategoryError
) -> JSONResponse:
    status_codes = {
        FinancialCategoryNotFoundError: status.HTTP_404_NOT_FOUND,
        FinancialCategoryConflictError: status.HTTP_409_CONFLICT,
        InvalidFinancialCategoryPaginationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    status_code = next(
        (
            code
            for error_type, code in status_codes.items()
            if isinstance(exc, error_type)
        ),
        500,
    )
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc) if status_code != 500 else "Internal server error"},
    )


CurrentBusinessId = Annotated[UUID, Depends(get_current_business_id)]
FinancialCategoryServiceDep = Annotated[
    FinancialCategoryService, Depends(get_financial_category_service)
]


@router.post(
    "", response_model=FinancialCategoryResponse, status_code=status.HTTP_201_CREATED
)
def create_financial_category(
    data: FinancialCategoryCreate,
    business_id: CurrentBusinessId,
    service: FinancialCategoryServiceDep,
) -> FinancialCategory:
    return service.create(data, business_id=business_id)


@router.get("", response_model=list[FinancialCategoryResponse])
def list_financial_categories(
    business_id: CurrentBusinessId,
    service: FinancialCategoryServiceDep,
    category_type: Annotated[FinancialType | None, Query(alias="type")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[FinancialCategory]:
    return service.list(
        business_id=business_id, category_type=category_type, offset=offset, limit=limit
    )


@router.get("/{category_id}", response_model=FinancialCategoryResponse)
def get_financial_category(
    category_id: UUID4,
    business_id: CurrentBusinessId,
    service: FinancialCategoryServiceDep,
) -> FinancialCategory:
    return service.get_by_id(category_id, business_id=business_id)


@router.patch("/{category_id}", response_model=FinancialCategoryResponse)
def update_financial_category(
    category_id: UUID4,
    data: FinancialCategoryUpdate,
    business_id: CurrentBusinessId,
    service: FinancialCategoryServiceDep,
) -> FinancialCategory:
    return service.update(category_id, data, business_id=business_id)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financial_category(
    category_id: UUID4,
    business_id: CurrentBusinessId,
    service: FinancialCategoryServiceDep,
) -> Response:
    service.delete(category_id, business_id=business_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
