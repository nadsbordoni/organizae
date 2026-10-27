from typing import Annotated
from uuid import UUID

from pydantic import (
    UUID4,
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.modules.services.schemas import ServiceResponse

ProfessionalName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
ProfessionalPhone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]


def validate_unique_service_ids(service_ids: list[UUID]) -> list[UUID]:
    if len(service_ids) != len(set(service_ids)):
        raise ValueError("service_ids must not contain duplicates")
    return service_ids


ServiceIds = Annotated[list[UUID4], AfterValidator(validate_unique_service_ids)]


class ProfessionalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: UUID4
    name: ProfessionalName
    phone: ProfessionalPhone | None = None
    description: str | None = None
    is_active: bool = True
    service_ids: ServiceIds = Field(default_factory=list)


class ProfessionalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProfessionalName | None = None
    phone: ProfessionalPhone | None = None
    description: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "ProfessionalUpdate":
        for field_name in ("name", "is_active"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class ProfessionalServicesUpdate(BaseModel):
    """Replace all service associations; an empty list clears the associations."""

    model_config = ConfigDict(extra="forbid")

    service_ids: ServiceIds


class ProfessionalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID4
    business_id: UUID4
    name: ProfessionalName
    phone: ProfessionalPhone | None = None
    description: str | None = None
    is_active: bool
    services: list[ServiceResponse]
