from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import UUID4, AwareDatetime
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.appointments.exceptions import (
    AppointmentConflictError,
    AppointmentError,
    AppointmentNotFoundError,
    InvalidBookingError,
)
from app.modules.appointments.models import Appointment, BusinessHour
from app.modules.appointments.schemas import (
    AppointmentResponse,
    AppointmentStatusUpdate,
    BlockCreateRequest,
    BusinessHourItem,
    BusinessHoursUpdate,
    OnlineBookingRequest,
    OnlineBookingResponse,
    PublicProfessionalResponse,
    PublicServiceResponse,
)
from app.modules.appointments.service import AppointmentService
from app.modules.auth.dependencies import get_current_business_id
from app.modules.professionals.models import Professional
from app.modules.services.models import Service

# Public pages of each business, no authentication.
public_router = APIRouter(
    prefix="/public/businesses/{business_id}", tags=["Online booking"]
)
router = APIRouter(tags=["Appointments"])


def get_appointment_service(
    session: Annotated[Session, Depends(get_db)],
) -> AppointmentService:
    return AppointmentService(session, ZoneInfo(settings.BUSINESS_TIMEZONE))


async def appointment_error_handler(
    request: Request, exc: AppointmentError
) -> JSONResponse:
    status_codes = {
        AppointmentNotFoundError: status.HTTP_404_NOT_FOUND,
        AppointmentConflictError: status.HTTP_409_CONFLICT,
        InvalidBookingError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
    status_code = status_codes.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    detail = str(exc) if status_code != 500 else "Internal server error"
    return JSONResponse(status_code=status_code, content={"detail": detail})


ServiceDep = Annotated[AppointmentService, Depends(get_appointment_service)]
CurrentBusinessId = Annotated[UUID, Depends(get_current_business_id)]


@public_router.get("/services", response_model=list[PublicServiceResponse])
def list_public_services(business_id: UUID4, service: ServiceDep) -> list[Service]:
    return service.list_public_services(business_id=business_id)


@public_router.get("/professionals", response_model=list[PublicProfessionalResponse])
def list_public_professionals(
    business_id: UUID4, service_id: UUID4, service: ServiceDep
) -> list[Professional]:
    return service.list_public_professionals(
        business_id=business_id, service_id=service_id
    )


@public_router.get("/availability", response_model=list[datetime])
def get_availability(
    business_id: UUID4,
    service_id: UUID4,
    professional_id: UUID4,
    day: Annotated[date, Query(alias="date")],
    service: ServiceDep,
) -> list[datetime]:
    return service.get_availability(
        business_id=business_id,
        service_id=service_id,
        professional_id=professional_id,
        day=day,
    )


@public_router.post(
    "/appointments",
    response_model=OnlineBookingResponse,
    status_code=status.HTTP_201_CREATED,
)
def book_online(
    business_id: UUID4, booking: OnlineBookingRequest, service: ServiceDep
) -> Appointment:
    return service.book_online(booking, business_id=business_id)


@router.get("/business-hours", response_model=list[BusinessHourItem])
def get_business_hours(
    business_id: CurrentBusinessId, service: ServiceDep
) -> list[BusinessHour]:
    return service.get_hours(business_id=business_id)


@router.put("/business-hours", response_model=list[BusinessHourItem])
def replace_business_hours(
    hours_data: BusinessHoursUpdate,
    business_id: CurrentBusinessId,
    service: ServiceDep,
) -> list[BusinessHour]:
    return service.replace_hours(hours_data, business_id=business_id)


@router.get("/appointments", response_model=list[AppointmentResponse])
def list_appointments(
    starts_at: AwareDatetime,
    ends_at: AwareDatetime,
    business_id: CurrentBusinessId,
    service: ServiceDep,
) -> list[Appointment]:
    return service.list_appointments(business_id=business_id, starts_at=starts_at, ends_at=ends_at)


@router.post(
    "/appointments/blocks",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_block(
    block: BlockCreateRequest, business_id: CurrentBusinessId, service: ServiceDep
) -> Appointment:
    return service.create_block(block, business_id=business_id)


@router.patch("/appointments/{appointment_id}/status", response_model=AppointmentResponse)
def update_appointment_status(
    appointment_id: UUID4,
    status_data: AppointmentStatusUpdate,
    business_id: CurrentBusinessId,
    service: ServiceDep,
) -> Appointment:
    return service.update_status(appointment_id, status_data, business_id=business_id)
