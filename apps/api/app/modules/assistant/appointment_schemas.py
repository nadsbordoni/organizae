from datetime import date
from typing import Self

from pydantic import UUID4, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modules.appointments.models import AppointmentStatus
from app.modules.appointments.schemas import Notes
from app.modules.appointments.service import MAX_LISTING_RANGE
from app.modules.clients.schemas import ClientPhone


class AppointmentListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    ends_at: AwareDatetime
    professional_id: UUID4 | None = None
    service_id: UUID4 | None = None
    status: AppointmentStatus | None = None
    customer_phone: ClientPhone | None = None
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=20, ge=1, le=50, strict=True)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (
            self.ends_at <= self.starts_at
            or self.ends_at - self.starts_at > MAX_LISTING_RANGE
        ):
            raise ValueError("Range must be positive and at most 31 days")
        return self


class AvailabilityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: UUID4
    professional_id: UUID4
    day: date
    limit: int = Field(default=20, ge=1, le=50, strict=True)


class AppointmentCreateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID4
    service_id: UUID4
    professional_id: UUID4
    starts_at: AwareDatetime
    notes: Notes | None = None
