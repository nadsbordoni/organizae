from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.services.exceptions import (
    InvalidServicePaginationError,
    ServiceConflictError,
    ServiceError,
    ServiceNotFoundError,
)
from app.modules.services.models import Service
from app.modules.services.schemas import ServiceCreate, ServiceResponse, ServiceUpdate
from app.modules.services.service import ServiceService

router = APIRouter(prefix="/services", tags=["Services"])


def get_service_service(
    session: Annotated[Session, Depends(get_db)],
) -> ServiceService:
    return ServiceService(session)


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    status_codes = {
        ServiceNotFoundError: status.HTTP_404_NOT_FOUND,
        ServiceConflictError: status.HTTP_409_CONFLICT,
        InvalidServicePaginationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    status_code = next(
        (
            code
            for error_type, code in status_codes.items()
            if isinstance(exc, error_type)
        ),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    detail = (
        str(exc)
        if status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
        else "Internal server error"
    )
    return JSONResponse(status_code=status_code, content={"detail": detail})


@router.post("", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
def create_service(
    service_data: ServiceCreate,
    service: Annotated[ServiceService, Depends(get_service_service)],
) -> Service:
    return service.create(service_data)


@router.get("", response_model=list[ServiceResponse])
def list_services(
    business_id: Annotated[UUID4, Query()],
    service: Annotated[ServiceService, Depends(get_service_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[Service]:
    return service.list(business_id=business_id, offset=offset, limit=limit)


@router.get("/{service_id}", response_model=ServiceResponse)
def get_service(
    service_id: UUID4,
    business_id: Annotated[UUID4, Query()],
    service: Annotated[ServiceService, Depends(get_service_service)],
) -> Service:
    return service.get_by_id(service_id, business_id=business_id)


@router.patch("/{service_id}", response_model=ServiceResponse)
def update_service(
    service_id: UUID4,
    business_id: Annotated[UUID4, Query()],
    service_data: ServiceUpdate,
    service: Annotated[ServiceService, Depends(get_service_service)],
) -> Service:
    return service.update(service_id, service_data, business_id=business_id)


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(
    service_id: UUID4,
    business_id: Annotated[UUID4, Query()],
    service: Annotated[ServiceService, Depends(get_service_service)],
) -> Response:
    service.delete(service_id, business_id=business_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
