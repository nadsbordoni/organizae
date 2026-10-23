from decimal import Decimal
from typing import Annotated

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

ServiceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
ServicePrice = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
ServiceDuration = Annotated[int, Field(gt=0, le=1440)]


class ServiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: UUID4
    name: ServiceName
    price: ServicePrice
    duration_minutes: ServiceDuration
    description: str | None = None
    is_active: bool = True


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ServiceName | None = None
    price: ServicePrice | None = None
    duration_minutes: ServiceDuration | None = None
    description: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "ServiceUpdate":
        for field_name in ("name", "price", "duration_minutes", "is_active"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class ServiceResponse(ServiceCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID4
