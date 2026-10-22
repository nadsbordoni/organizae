from typing import Annotated

from app.modules.businesses.models import ServiceMode
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

BusinessName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
WhatsAppNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


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

    @model_validator(mode="after")
    def validate_required_fields(self) -> "BusinessUpdate":
        for field_name in ("name", "category_id", "whatsapp", "service_mode"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class BusinessResponse(BusinessCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
