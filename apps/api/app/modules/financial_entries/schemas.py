from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    UUID4,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.modules.financial_categories.models import FinancialType
from app.modules.financial_entries.models import FinancialEntryStatus

EntryDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
EntryAmount = Annotated[
    Decimal, Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
]


class FinancialEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID4
    type: FinancialType
    description: EntryDescription
    amount: EntryAmount
    due_date: date
    appointment_id: UUID4 | None = None


class FinancialEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID4 | None = None
    type: FinancialType | None = None
    description: EntryDescription | None = None
    amount: EntryAmount | None = None
    due_date: date | None = None
    appointment_id: UUID4 | None = None
    status: (
        Literal[FinancialEntryStatus.PENDING, FinancialEntryStatus.CANCELLED] | None
    ) = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "FinancialEntryUpdate":
        for field_name in (
            "category_id",
            "type",
            "description",
            "amount",
            "due_date",
            "status",
        ):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class FinancialEntryPayment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paid_at: AwareDatetime | None = None


class FinancialEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    business_id: UUID4
    category_id: UUID4
    type: FinancialType
    description: EntryDescription
    amount: Decimal
    due_date: date
    paid_at: datetime | None
    status: FinancialEntryStatus
    appointment_id: UUID4 | None
    created_at: datetime
    recurring_entry_id: UUID4 | None
    competence: date | None
