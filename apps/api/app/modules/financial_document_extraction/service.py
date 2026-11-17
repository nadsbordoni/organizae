import json
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.assistant.exceptions import AssistantInvalidResponseError
from app.modules.businesses.service import BusinessService
from app.modules.financial_categories.service import FinancialCategoryService
from app.modules.financial_document_extraction.documents import validate_document
from app.modules.financial_document_extraction.exceptions import DocumentDatabaseError
from app.modules.financial_document_extraction.prompts import EXTRACTION_PROMPT
from app.modules.financial_document_extraction.schemas import (
    ExtractedFinancialData,
    FieldAssessment,
    FieldName,
    FinancialDocumentExtractionResponse,
    FinancialDocumentReading,
)
from app.modules.financial_entries.models import FinancialEntryStatus


class DocumentExtractionProvider(Protocol):
    def extract_financial_document(
        self, data: bytes, *, mime_type: str, system_prompt: str, context: str
    ) -> FinancialDocumentReading: ...


class FinancialDocumentExtractionService:
    def __init__(self, session: Session, provider: DocumentExtractionProvider) -> None:
        self.session = session
        self.provider = provider
        self.categories = FinancialCategoryService(session)
        self.businesses = BusinessService(session)

    def extract(
        self, data: bytes, *, business_id: UUID
    ) -> FinancialDocumentExtractionResponse:
        mime_type = validate_document(data)
        try:
            business = self.businesses.get_by_id(business_id)
            categories = []
            while True:
                page = self.categories.list(
                    business_id=business_id, offset=len(categories), limit=100
                )
                categories.extend(page)
                if len(page) < 100:
                    break
            # Only company name and category labels are needed to classify direction.
            context = json.dumps(
                {
                    "business_name": business.name,
                    "categories": [
                        {"id": str(item.id), "name": item.name, "type": item.type.value}
                        for item in categories
                    ],
                },
                ensure_ascii=False,
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DocumentDatabaseError() from exc
        reading = self.provider.extract_financial_document(
            data, mime_type=mime_type, system_prompt=EXTRACTION_PROMPT, context=context
        )
        try:
            reading = FinancialDocumentReading.model_validate(reading)
        except ValidationError as exc:
            raise AssistantInvalidResponseError() from exc
        values = reading.extracted_data.model_copy(deep=True)
        assessments = {item.field: item for item in reading.field_assessments}
        if len(assessments) != len(reading.field_assessments):
            raise AssistantInvalidResponseError()
        warnings = []
        if reading.readability == "unreadable":
            values = ExtractedFinancialData()
            warnings.append(
                "O documento está ilegível. Envie uma imagem ou PDF mais nítido."
            )
        if reading.contradictory:
            # No field in a contradictory document is safe to autofill.
            values = ExtractedFinancialData()
            warnings.append(
                "Há informações contraditórias; confira o documento manualmente."
            )
        if reading.readability == "partial":
            warnings.append("Parte do documento não pôde ser lida com segurança.")
        for name in ExtractedFinancialData.model_fields:
            assessment = assessments.get(name)
            if assessment is None or assessment.source == "unknown":
                setattr(values, name, None)
        confirmed = reading.payment_confirmed and bool(
            reading.payment_evidence and reading.payment_evidence.strip()
        )
        if not confirmed or values.status != FinancialEntryStatus.PAID:
            values.payment_date = None
            if values.status == FinancialEntryStatus.PAID:
                values.status = None
                warnings.append(
                    "Pagamento não comprovado; situação e data de pagamento não preenchidas."
                )
        if values.scheduled is True and values.status == FinancialEntryStatus.PAID:
            values.status = None
            values.payment_date = None
            warnings.append(
                "Documento mistura agendamento e quitação; confirme a situação."
            )
        if values.category_id is not None:
            category = next(
                (item for item in categories if item.id == values.category_id), None
            )
            if category is None or values.type is None or category.type != values.type:
                values.category_id = None
                warnings.append(
                    "A categoria sugerida não corresponde às categorias e ao tipo da empresa."
                )
        if values.category_id is None:
            warnings.append("Não foi possível identificar uma categoria com segurança.")
        else:
            assessments["category_id"] = assessments["category_id"].model_copy(
                update={"source": "suggested"}
            )
        final_assessments = []
        missing: list[FieldName] = []
        for name in ExtractedFinancialData.model_fields:
            if getattr(values, name) is None:
                missing.append(name)
                final_assessments.append(FieldAssessment(field=name, source="unknown"))
            else:
                final_assessments.append(assessments[name])
        if missing:
            warnings.append(
                "Há campos não identificados. Revise e complete antes de salvar."
            )
        return FinancialDocumentExtractionResponse(
            document_type=reading.document_type,
            readability=reading.readability,
            extracted_data=values,
            field_assessments=final_assessments,
            missing_fields=missing,
            warnings=warnings,
        )
