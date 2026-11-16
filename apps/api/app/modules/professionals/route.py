from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_business_id
from app.modules.professionals.exceptions import (
    InvalidProfessionalPaginationError,
    InvalidProfessionalServicesError,
    ProfessionalConflictError,
    ProfessionalError,
    ProfessionalNotFoundError,
)
from app.modules.professionals.models import Professional
from app.modules.professionals.schemas import (
    ProfessionalCreate,
    ProfessionalCreateRequest,
    ProfessionalResponse,
    ProfessionalServicesUpdate,
    ProfessionalUpdate,
)
from app.modules.professionals.service import ProfessionalService

router = APIRouter(prefix="/professionals", tags=["Professionals"])


def get_professional_service(
    session: Annotated[Session, Depends(get_db)],
) -> ProfessionalService:
    return ProfessionalService(session)


async def professional_error_handler(
    request: Request, exc: ProfessionalError
) -> JSONResponse:
    status_codes = {
        ProfessionalNotFoundError: status.HTTP_404_NOT_FOUND,
        ProfessionalConflictError: status.HTTP_409_CONFLICT,
        InvalidProfessionalServicesError: status.HTTP_422_UNPROCESSABLE_CONTENT,
        InvalidProfessionalPaginationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
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


@router.post(
    "", response_model=ProfessionalResponse, status_code=status.HTTP_201_CREATED
)
def create_professional(
    professional_data: ProfessionalCreateRequest,
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    service: Annotated[ProfessionalService, Depends(get_professional_service)],
) -> Professional:
    return service.create(
        ProfessionalCreate(**professional_data.model_dump(), business_id=business_id)
    )


@router.get("", response_model=list[ProfessionalResponse])
def list_professionals(
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    service: Annotated[ProfessionalService, Depends(get_professional_service)],
    is_active: Annotated[
        bool | None,
        Query(description="Omit to include active and inactive professionals"),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[Professional]:
    return service.list(
        business_id=business_id, is_active=is_active, offset=offset, limit=limit
    )


@router.get("/{professional_id}", response_model=ProfessionalResponse)
def get_professional(
    professional_id: UUID4,
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    service: Annotated[ProfessionalService, Depends(get_professional_service)],
) -> Professional:
    return service.get_by_id(professional_id, business_id=business_id)


@router.patch("/{professional_id}", response_model=ProfessionalResponse)
def update_professional(
    professional_id: UUID4,
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    professional_data: ProfessionalUpdate,
    service: Annotated[ProfessionalService, Depends(get_professional_service)],
) -> Professional:
    return service.update(professional_id, professional_data, business_id=business_id)


@router.put("/{professional_id}/services", response_model=ProfessionalResponse)
def replace_professional_services(
    professional_id: UUID4,
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    services_data: ProfessionalServicesUpdate,
    service: Annotated[ProfessionalService, Depends(get_professional_service)],
) -> Professional:
    return service.replace_services(
        professional_id, services_data, business_id=business_id
    )


@router.delete(
    "/{professional_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a professional while preserving service associations",
)
def delete_professional(
    professional_id: UUID4,
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    service: Annotated[ProfessionalService, Depends(get_professional_service)],
) -> Response:
    service.delete(professional_id, business_id=business_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
