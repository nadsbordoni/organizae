from typing import Annotated

from pydantic import UUID4, BaseModel, ConfigDict, StringConstraints, model_validator

from app.modules.financial_categories.models import FinancialType

FinancialCategoryName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]


class FinancialCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: FinancialCategoryName
    type: FinancialType


class FinancialCategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: FinancialCategoryName | None = None
    type: FinancialType | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "FinancialCategoryUpdate":
        for field_name in ("name", "type"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class FinancialCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    business_id: UUID4
    name: FinancialCategoryName
    type: FinancialType
