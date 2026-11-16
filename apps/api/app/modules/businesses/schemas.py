import re
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


def normalize_instagram_handle(value: str) -> str:
    # Stored without "@" so the front-end can build the profile link directly.
    handle = value.strip().removeprefix("@")
    if not INSTAGRAM_HANDLE_PATTERN.fullmatch(handle):
        raise ValueError(
            "instagram must have up to 30 letters, numbers, dots or underscores"
        )
    return handle


BusinessName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
WhatsAppNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]
InstagramHandle = Annotated[str, AfterValidator(normalize_instagram_handle)]


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
    instagram: InstagramHandle | None = None


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
    instagram: InstagramHandle | None = None

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
