from datetime import date
from decimal import Decimal

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

from app.modules.financial_categories.models import FinancialType
from app.modules.financial_entries.schemas import (
    EntryAmount,
    EntryDescription,
    FinancialEntryResponse,
)


class RecurringEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID4
    type: FinancialType
    description: EntryDescription
    amount: EntryAmount
    due_day: int = Field(ge=1, le=31, strict=True)
    start_date: date
    end_date: date | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> "RecurringEntryCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("End date must not precede start date")
        return self


class RecurringEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID4 | None = None
    type: FinancialType | None = None
    description: EntryDescription | None = None
    amount: EntryAmount | None = None
    due_day: int | None = Field(default=None, ge=1, le=31, strict=True)
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "RecurringEntryUpdate":
        for field_name in self.model_fields_set - {"end_date"}:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("End date must not precede start date")
        return self


class RecurringEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    business_id: UUID4
    category_id: UUID4
    type: FinancialType
    description: str
    amount: Decimal
    due_day: int
    start_date: date
    end_date: date | None
    is_active: bool


class RecurringEntryGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_month: date
    end_month: date

    @model_validator(mode="after")
    def validate_period(self) -> "RecurringEntryGenerate":
        if self.start_month.day != 1 or self.end_month.day != 1:
            raise ValueError("Competences must use the first day of the month")
        months = (
            (self.end_month.year - self.start_month.year) * 12
            + self.end_month.month
            - self.start_month.month
        )
        if not 0 <= months < 12:
            raise ValueError("Generation period must contain between 1 and 12 months")
        return self


class RecurringEntryGenerationResponse(BaseModel):
    created_entries: list[FinancialEntryResponse]
    skipped_competences: list[date]
