import re
from datetime import datetime
from typing import Annotated

from pydantic import (
    UUID4,
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    StringConstraints,
    model_validator,
)


def normalize_phone(value: str) -> str:
    digits = re.sub(r"[^0-9]", "", value)
    if not 10 <= len(digits) <= 13:
        raise ValueError("phone must have 10 to 13 digits, including area code")
    return digits


ClientName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ClientPhone = Annotated[
    str, StringConstraints(max_length=40), AfterValidator(normalize_phone)
]
ClientEmail = Annotated[EmailStr, StringConstraints(max_length=255)]
ClientNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ClientName
    phone: ClientPhone
    email: ClientEmail | None = None
    notes: ClientNotes | None = None


class ClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ClientName | None = None
    phone: ClientPhone | None = None
    email: ClientEmail | None = None
    notes: ClientNotes | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "ClientUpdate":
        for field_name in ("name", "phone"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    business_id: UUID4
    name: str
    phone: str
    email: str | None
    notes: str | None
    created_at: datetime
