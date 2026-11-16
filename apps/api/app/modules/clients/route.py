from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.appointments.models import Appointment
from app.modules.appointments.schemas import AppointmentResponse
from app.modules.auth.dependencies import get_current_business_id
from app.modules.clients.exceptions import (
    ClientConflictError,
    ClientError,
    ClientNotFoundError,
    InvalidClientPaginationError,
)
from app.modules.clients.models import Client
from app.modules.clients.schemas import ClientCreate, ClientResponse, ClientUpdate
from app.modules.clients.service import ClientService

router = APIRouter(prefix="/clients", tags=["Clients"])


def get_client_service(session: Annotated[Session, Depends(get_db)]) -> ClientService:
    return ClientService(session)


async def client_error_handler(request: Request, exc: ClientError) -> JSONResponse:
    status_codes = {
        ClientNotFoundError: status.HTTP_404_NOT_FOUND,
        ClientConflictError: status.HTTP_409_CONFLICT,
        InvalidClientPaginationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
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
ClientServiceDep = Annotated[ClientService, Depends(get_client_service)]


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    client_data: ClientCreate, business_id: CurrentBusinessId, service: ClientServiceDep
) -> Client:
    return service.create(client_data, business_id=business_id)


@router.get("", response_model=list[ClientResponse])
def list_clients(
    business_id: CurrentBusinessId,
    service: ClientServiceDep,
    search: Annotated[str | None, Query(max_length=255)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[Client]:
    return service.list(
        business_id=business_id, search=search, offset=offset, limit=limit
    )


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: UUID4, business_id: CurrentBusinessId, service: ClientServiceDep
) -> Client:
    return service.get_by_id(client_id, business_id=business_id)


@router.patch("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: UUID4,
    client_data: ClientUpdate,
    business_id: CurrentBusinessId,
    service: ClientServiceDep,
) -> Client:
    return service.update(client_id, client_data, business_id=business_id)


@router.get("/{client_id}/appointments", response_model=list[AppointmentResponse])
def list_client_appointments(
    client_id: UUID4,
    business_id: CurrentBusinessId,
    service: ClientServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[Appointment]:
    return service.list_appointments(
        client_id, business_id=business_id, offset=offset, limit=limit
    )
