import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    UUID4,
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.businesses.models import ServiceMode

INSTAGRAM_HANDLE_PATTERN = re.compile(r"[A-Za-z0-9._]{1,30}")
TAX_ID_SEPARATORS = re.compile(r"[\s./-]")
TAX_ID_PATTERN = re.compile(r"[0-9]{11}|[0-9A-Z]{12}[0-9]{2}")
CNPJ_WEIGHTS = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def normalize_instagram_handle(value: str) -> str:
    # Stored without "@" so the front-end can build the profile link directly.
    handle = value.strip().removeprefix("@")
    if not INSTAGRAM_HANDLE_PATTERN.fullmatch(handle):
        raise ValueError(
            "instagram must have up to 30 letters, numbers, dots or underscores"
        )
    return handle


def _check_digit(values: list[int], weights: Iterable[int]) -> int:
    total = sum(value * weight for value, weight in zip(values, weights, strict=True))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def normalize_tax_id(value: str) -> str:
    """Accept a CPF or a CNPJ, with or without punctuation, and keep only its characters."""
    tax_id = TAX_ID_SEPARATORS.sub("", value).upper()
    if not TAX_ID_PATTERN.fullmatch(tax_id):
        raise ValueError(
            "tax_id must be a CPF with 11 digits or a CNPJ with 14 characters"
        )

    # The alphanumeric CNPJ counts each character as its ASCII code minus 48,
    # which keeps 0-9 with their usual value.
    values = [ord(char) - 48 for char in tax_id]
    base = values[:-2]
    if len(tax_id) == 11:
        first_weights, second_weights = range(10, 1, -1), range(11, 1, -1)
    else:
        first_weights, second_weights = CNPJ_WEIGHTS, (6, *CNPJ_WEIGHTS)
    first = _check_digit(base, first_weights)
    second = _check_digit([*base, first], second_weights)
    # Repeated characters such as 111.111.111-11 pass the arithmetic but are not valid.
    if len(set(tax_id)) == 1 or values[-2:] != [first, second]:
        raise ValueError("tax_id is not a valid CPF or CNPJ")
    return tax_id


BusinessName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
WhatsAppNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]
InstagramHandle = Annotated[str, AfterValidator(normalize_instagram_handle)]
CityName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
TaxId = Annotated[
    str, StringConstraints(max_length=20), AfterValidator(normalize_tax_id)
]


class BusinessCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: BusinessName
    category_id: int = Field(gt=0)
    whatsapp: WhatsAppNumber
    service_mode: ServiceMode
    logo_url: str | None = Field(default=None, max_length=500)
    description: str | None = None
    external_link: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    city: CityName | None = None
    instagram: InstagramHandle | None = None
    tax_id: TaxId | None = None


class BusinessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: BusinessName | None = None
    category_id: int | None = Field(default=None, gt=0)
    whatsapp: WhatsAppNumber | None = None
    service_mode: ServiceMode | None = None
    logo_url: str | None = Field(default=None, max_length=500)
    description: str | None = None
    external_link: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    city: CityName | None = None
    instagram: InstagramHandle | None = None
    tax_id: TaxId | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "BusinessUpdate":
        for field_name in ("name", "category_id", "whatsapp", "service_mode"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class BusinessResponse(BusinessCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID4
    slug: str | None = None
    is_published: bool = False
    published_at: datetime | None = None

    @field_validator("is_published", mode="before")
    @classmethod
    def default_unsaved_to_unpublished(cls, value: bool | None) -> bool:
        # The column default is only applied on flush; before that it is None.
        return bool(value)


class PublicPageServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    name: str
    description: str | None
    price: Decimal
    duration_minutes: int


class PublicPageResponse(BaseModel):
    """Data shown to anyone who opens a published business page."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    slug: str
    name: str
    logo_url: str | None
    description: str | None
    whatsapp: str
    instagram: str | None
    address: str | None
    service_mode: ServiceMode
    services: list[PublicPageServiceResponse]
