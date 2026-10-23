from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.businesses.exceptions import (
    BusinessCategoryNotFoundError,
    BusinessConflictError,
    BusinessError,
    BusinessNotFoundError,
    InvalidBusinessPaginationError,
)
from app.modules.businesses.models import Business
from app.modules.businesses.schemas import (
    BusinessCreate,
    BusinessResponse,
    BusinessUpdate,
)
from app.modules.businesses.service import BusinessService

router = APIRouter(prefix="/businesses", tags=["Businesses"])


def get_business_service(
    session: Annotated[Session, Depends(get_db)],
) -> BusinessService:
    return BusinessService(session)


async def business_error_handler(request: Request, exc: BusinessError) -> JSONResponse:
    status_codes = {
        BusinessNotFoundError: status.HTTP_404_NOT_FOUND,
        BusinessCategoryNotFoundError: status.HTTP_422_UNPROCESSABLE_CONTENT,
        BusinessConflictError: status.HTTP_409_CONFLICT,
        InvalidBusinessPaginationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    status_code = status_codes.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    detail = str(exc) if status_code != 500 else "Internal server error"
    return JSONResponse(status_code=status_code, content={"detail": detail})


@router.post("", response_model=BusinessResponse, status_code=status.HTTP_201_CREATED)
def create_business(
    business_data: BusinessCreate,
    service: Annotated[BusinessService, Depends(get_business_service)],
) -> Business:
    return service.create(business_data)


@router.get("", response_model=list[BusinessResponse])
def list_businesses(
    service: Annotated[BusinessService, Depends(get_business_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(gt=0, le=100)] = 100,
) -> list[Business]:
    return service.list(offset=offset, limit=limit)


@router.get("/{business_id}", response_model=BusinessResponse)
def get_business(
    business_id: UUID4,
    service: Annotated[BusinessService, Depends(get_business_service)],
) -> Business:
    return service.get_by_id(business_id)


@router.patch("/{business_id}", response_model=BusinessResponse)
def update_business(
    business_id: UUID4,
    business_data: BusinessUpdate,
    service: Annotated[BusinessService, Depends(get_business_service)],
) -> Business:
    return service.update(business_id, business_data)


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business(
    business_id: UUID4,
    service: Annotated[BusinessService, Depends(get_business_service)],
) -> Response:
    service.delete(business_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
