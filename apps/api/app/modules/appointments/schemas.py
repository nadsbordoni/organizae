import re
from datetime import datetime, time
from decimal import Decimal
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import (
    UUID4,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.appointments.models import AppointmentSource, AppointmentStatus

Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class BusinessHourItem(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    weekday: Annotated[int, Field(ge=0, le=6)]
    opens_at: time
    closes_at: time

    @model_validator(mode="after")
    def validate_range(self) -> "BusinessHourItem":
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be after opens_at")
        return self


class BusinessHoursUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: Annotated[list[BusinessHourItem], Field(max_length=28)]

    @model_validator(mode="after")
    def validate_no_overlap(self) -> "BusinessHoursUpdate":
        ordered = sorted(self.hours, key=lambda h: (h.weekday, h.opens_at))
        for previous, current in pairwise(ordered):
            if (
                previous.weekday == current.weekday
                and current.opens_at < previous.closes_at
            ):
                raise ValueError("business hours overlap on the same weekday")
        return self


class PublicServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    name: str
    description: str | None
    price: Decimal
    duration_minutes: int


class PublicProfessionalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    name: str
    description: str | None


class OnlineBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: UUID4
    professional_id: UUID4
    starts_at: AwareDatetime
    customer_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)
    ]
    customer_phone: str
    customer_email: EmailStr | None = None
    notes: Notes | None = None

    @field_validator("customer_phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if not 10 <= len(digits) <= 13:
            raise ValueError("phone must have 10 to 13 digits, including area code")
        return digits


class OnlineBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus


class BlockCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    professional_id: UUID4 | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    notes: Notes | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "BlockCreateRequest":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AppointmentStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED]


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    business_id: UUID4
    professional_id: UUID4 | None
    service_id: UUID4 | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None
    notes: str | None
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    source: AppointmentSource
    created_at: datetime
