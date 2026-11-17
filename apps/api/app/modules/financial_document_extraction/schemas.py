from datetime import date
from typing import Annotated, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field

from app.modules.financial_categories.models import FinancialType
from app.modules.financial_entries.models import FinancialEntryStatus
from app.modules.financial_entries.schemas import EntryAmount, EntryDescription

FieldName = Literal[
    "type",
    "description",
    "amount",
    "category_id",
    "competence_date",
    "payment_date",
    "due_date",
    "status",
    "payment_method",
    "scheduled",
]


class ExtractedFinancialData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: FinancialType | None = None
    description: EntryDescription | None = None
    amount: EntryAmount | None = None
    category_id: UUID4 | None = None
    competence_date: date | None = None
    payment_date: date | None = None
    due_date: date | None = None
    status: FinancialEntryStatus | None = None
    payment_method: Literal["pix", "card", "cash", "boleto", "debit"] | None = None
    scheduled: bool | None = None


class FieldAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: FieldName
    source: Literal["extracted", "suggested", "unknown"]
    evidence: Annotated[str, Field(max_length=300)] | None = None


class FinancialDocumentReading(BaseModel):
    """Validated model output, before business-scoped category checks."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["receipt", "invoice", "payment_receipt", "other", "unknown"]
    readability: Literal["readable", "partial", "unreadable"]
    contradictory: bool
    payment_confirmed: bool
    payment_evidence: Annotated[str, Field(max_length=300)] | None
    extracted_data: ExtractedFinancialData
    field_assessments: list[FieldAssessment] = Field(max_length=10)


class FinancialDocumentExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["receipt", "invoice", "payment_receipt", "other", "unknown"]
    readability: Literal["readable", "partial", "unreadable"]
    extracted_data: ExtractedFinancialData
    field_assessments: list[FieldAssessment]
    missing_fields: list[FieldName]
    warnings: list[str]
    requires_review: Literal[True] = True
