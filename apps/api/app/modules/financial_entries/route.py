from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_business_id
from app.modules.financial_categories.models import FinancialType
from app.modules.financial_entries.exceptions import (
    FinancialEntryConflictError,
    FinancialEntryError,
    FinancialEntryNotFoundError,
    InvalidFinancialEntryError,
)
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.schemas import (
    FinancialEntryCreate,
    FinancialEntryPayment,
    FinancialEntryResponse,
    FinancialEntryUpdate,
)
from app.modules.financial_entries.service import FinancialEntryService

router = APIRouter(prefix="/financial-entries", tags=["Financial entries"])


def get_financial_entry_service(
    session: Annotated[Session, Depends(get_db)],
) -> FinancialEntryService:
    return FinancialEntryService(session)


async def financial_entry_error_handler(
    request: Request, exc: FinancialEntryError
) -> JSONResponse:
    status_codes = {
        FinancialEntryNotFoundError: status.HTTP_404_NOT_FOUND,
        FinancialEntryConflictError: status.HTTP_409_CONFLICT,
        InvalidFinancialEntryError: status.HTTP_422_UNPROCESSABLE_CONTENT,
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
FinancialEntryServiceDep = Annotated[
    FinancialEntryService, Depends(get_financial_entry_service)
]


@router.post(
    "", response_model=FinancialEntryResponse, status_code=status.HTTP_201_CREATED
)
def create_financial_entry(
    data: FinancialEntryCreate,
    business_id: CurrentBusinessId,
    service: FinancialEntryServiceDep,
) -> FinancialEntry:
    return service.create(data, business_id=business_id)


@router.get("", response_model=list[FinancialEntryResponse])
def list_financial_entries(
    business_id: CurrentBusinessId,
    service: FinancialEntryServiceDep,
    start_date: date | None = None,
    end_date: date | None = None,
    entry_type: Annotated[FinancialType | None, Query(alias="type")] = None,
    category_id: UUID4 | None = None,
    status: FinancialEntryStatus | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[FinancialEntry]:
    return service.list(
        business_id=business_id,
        start_date=start_date,
        end_date=end_date,
        entry_type=entry_type,
        category_id=category_id,
        status=status,
        offset=offset,
        limit=limit,
    )


@router.get("/{entry_id}", response_model=FinancialEntryResponse)
def get_financial_entry(
    entry_id: UUID4, business_id: CurrentBusinessId, service: FinancialEntryServiceDep
) -> FinancialEntry:
    return service.get_by_id(entry_id, business_id=business_id)


@router.patch("/{entry_id}", response_model=FinancialEntryResponse)
def update_financial_entry(
    entry_id: UUID4,
    data: FinancialEntryUpdate,
    business_id: CurrentBusinessId,
    service: FinancialEntryServiceDep,
) -> FinancialEntry:
    return service.update(entry_id, data, business_id=business_id)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financial_entry(
    entry_id: UUID4, business_id: CurrentBusinessId, service: FinancialEntryServiceDep
) -> Response:
    service.delete(entry_id, business_id=business_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{entry_id}/pay", response_model=FinancialEntryResponse)
def pay_financial_entry(
    entry_id: UUID4,
    data: FinancialEntryPayment,
    business_id: CurrentBusinessId,
    service: FinancialEntryServiceDep,
) -> FinancialEntry:
    return service.pay(entry_id, data, business_id=business_id)
