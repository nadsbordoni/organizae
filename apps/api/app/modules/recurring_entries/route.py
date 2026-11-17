from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_business_id
from app.modules.financial_categories.models import FinancialType
from app.modules.recurring_entries.exceptions import (
    InvalidRecurringEntryError,
    RecurringEntryConflictError,
    RecurringEntryError,
    RecurringEntryNotFoundError,
)
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.recurring_entries.schemas import (
    RecurringEntryCreate,
    RecurringEntryGenerate,
    RecurringEntryGenerationResponse,
    RecurringEntryResponse,
    RecurringEntryUpdate,
)
from app.modules.recurring_entries.service import RecurringEntryService

router = APIRouter(prefix="/recurring-entries", tags=["Recurring entries"])


def get_recurring_entry_service(
    session: Annotated[Session, Depends(get_db)],
) -> RecurringEntryService:
    return RecurringEntryService(session)


async def recurring_entry_error_handler(
    request: Request, exc: RecurringEntryError
) -> JSONResponse:
    status_codes = {
        RecurringEntryNotFoundError: status.HTTP_404_NOT_FOUND,
        RecurringEntryConflictError: status.HTTP_409_CONFLICT,
        InvalidRecurringEntryError: status.HTTP_422_UNPROCESSABLE_CONTENT,
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
RecurringEntryServiceDep = Annotated[
    RecurringEntryService, Depends(get_recurring_entry_service)
]


@router.post(
    "", response_model=RecurringEntryResponse, status_code=status.HTTP_201_CREATED
)
def create_recurring_entry(
    data: RecurringEntryCreate,
    business_id: CurrentBusinessId,
    service: RecurringEntryServiceDep,
) -> RecurringEntry:
    return service.create(data, business_id=business_id)


@router.get("", response_model=list[RecurringEntryResponse])
def list_recurring_entries(
    business_id: CurrentBusinessId,
    service: RecurringEntryServiceDep,
    is_active: bool | None = None,
    entry_type: Annotated[FinancialType | None, Query(alias="type")] = None,
    category_id: UUID4 | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[RecurringEntry]:
    return service.list(
        business_id=business_id,
        is_active=is_active,
        entry_type=entry_type,
        category_id=category_id,
        offset=offset,
        limit=limit,
    )


@router.get("/{recurring_entry_id}", response_model=RecurringEntryResponse)
def get_recurring_entry(
    recurring_entry_id: UUID4,
    business_id: CurrentBusinessId,
    service: RecurringEntryServiceDep,
) -> RecurringEntry:
    return service.get_by_id(recurring_entry_id, business_id=business_id)


@router.patch("/{recurring_entry_id}", response_model=RecurringEntryResponse)
def update_recurring_entry(
    recurring_entry_id: UUID4,
    data: RecurringEntryUpdate,
    business_id: CurrentBusinessId,
    service: RecurringEntryServiceDep,
) -> RecurringEntry:
    return service.update(recurring_entry_id, data, business_id=business_id)


@router.delete("/{recurring_entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring_entry(
    recurring_entry_id: UUID4,
    business_id: CurrentBusinessId,
    service: RecurringEntryServiceDep,
) -> Response:
    service.delete(recurring_entry_id, business_id=business_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{recurring_entry_id}/generate", response_model=RecurringEntryGenerationResponse
)
def generate_recurring_entries(
    recurring_entry_id: UUID4,
    data: RecurringEntryGenerate,
    business_id: CurrentBusinessId,
    service: RecurringEntryServiceDep,
) -> RecurringEntryGenerationResponse:
    return service.generate(recurring_entry_id, data, business_id=business_id)
