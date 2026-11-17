from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from python_multipart.exceptions import MultipartParseError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.config import settings
from app.db.session import get_db
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.auth.dependencies import get_current_business_id
from app.modules.financial_document_extraction.documents import MAX_DOCUMENT_BYTES
from app.modules.financial_document_extraction.exceptions import (
    DocumentComplexityError,
    DocumentDatabaseError,
    DocumentExtractionError,
    DocumentTooLargeError,
    UnsupportedDocumentError,
)
from app.modules.financial_document_extraction.schemas import (
    FinancialDocumentExtractionResponse,
)
from app.modules.financial_document_extraction.service import (
    FinancialDocumentExtractionService,
)

router = APIRouter(prefix="/financial", tags=["Financial document extraction"])


class UploadTooLarge(MultiPartException):
    pass


class DocumentMultipartParser(MultiPartParser):
    document_size: int = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_part.file is not None:
            self.document_size += end - start
            if self.document_size > MAX_DOCUMENT_BYTES:
                raise UploadTooLarge("Document exceeds 5 MB")
        super().on_part_data(data, start, end)

    def on_end(self) -> None:
        self.completed = True
        super().on_end()

    async def parse(self) -> FormData:
        self.completed = False
        form = await super().parse()
        if not self.completed:
            await form.close()
            raise MultiPartException("Incomplete multipart body")
        return form


def get_document_extraction_service(
    session: Annotated[Session, Depends(get_db)],
) -> FinancialDocumentExtractionService:
    return FinancialDocumentExtractionService(session, GeminiProvider(settings))


async def document_extraction_error_handler(
    request: Request, exc: DocumentExtractionError
) -> JSONResponse:
    code = 422
    if isinstance(exc, DocumentTooLargeError):
        code = 413
    elif isinstance(exc, UnsupportedDocumentError):
        code = 415
    elif isinstance(exc, DocumentDatabaseError):
        code = 503
    elif isinstance(exc, DocumentComplexityError):
        code = 422
    return JSONResponse(
        status_code=code, content={"code": exc.code, "detail": exc.public_message}
    )


@router.post(
    "/document-extraction",
    response_model=FinancialDocumentExtractionResponse,
    summary="Extrair prévia financeira de JPG, PNG ou PDF (até 5 MB)",
    description="Não salva arquivos nem cria lançamentos. Os dados devem ser revisados antes do cadastro.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
    responses={
        200: {
            "description": "Prévia para revisão; nenhum lançamento é criado",
            "content": {
                "application/json": {
                    "example": {
                        "document_type": "invoice",
                        "readability": "readable",
                        "extracted_data": {
                            "type": "EXPENSE",
                            "description": "Compra de materiais",
                            "amount": "150.00",
                            "category_id": None,
                            "competence_date": None,
                            "payment_date": None,
                            "due_date": "2026-11-20",
                            "status": None,
                            "payment_method": None,
                            "scheduled": None,
                        },
                        "field_assessments": [
                            {
                                "field": "amount",
                                "source": "extracted",
                                "evidence": "Total do documento",
                            }
                        ],
                        "missing_fields": [
                            "category_id",
                            "competence_date",
                            "payment_date",
                            "status",
                            "payment_method",
                            "scheduled",
                        ],
                        "warnings": [
                            "Não foi possível identificar uma categoria com segurança."
                        ],
                        "requires_review": True,
                    }
                }
            },
        },
        413: {"description": "Arquivo maior que 5 MB"},
        415: {"description": "Formato não suportado"},
        422: {"description": "Documento inválido ou formulário incorreto"},
    },
)
async def extract_financial_document(
    request: Request,
    response: Response,
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    service: Annotated[
        FinancialDocumentExtractionService, Depends(get_document_extraction_service)
    ],
) -> FinancialDocumentExtractionResponse:
    if request.query_params:
        raise HTTPException(
            status_code=422, detail="Este endpoint não aceita parâmetros de consulta."
        )

    # Parse only after authentication, rejecting extra fields and multiple uploads.
    async def limited_stream() -> AsyncIterator[bytes]:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_DOCUMENT_BYTES + 64 * 1024:
                raise UploadTooLarge("Multipart body exceeds limit")
            yield chunk

    if (
        not request.headers.get("content-type", "")
        .lower()
        .startswith("multipart/form-data")
    ):
        raise HTTPException(
            status_code=415, detail="Use multipart/form-data com o campo file."
        )
    parser = DocumentMultipartParser(
        request.headers, limited_stream(), max_files=1, max_fields=0
    )
    try:
        form = await parser.parse()
    except UploadTooLarge as exc:
        raise DocumentTooLargeError() from exc
    except (MultiPartException, MultipartParseError) as exc:
        raise HTTPException(
            status_code=422, detail="Envie somente um documento válido no campo file."
        ) from exc
    try:
        items = list(form.multi_items())
        if (
            len(items) != 1
            or items[0][0] != "file"
            or not isinstance(items[0][1], StarletteUploadFile)
        ):
            raise HTTPException(
                status_code=422, detail="Envie somente o arquivo no campo file."
            )
        file = items[0][1]
        data = await file.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            raise DocumentTooLargeError()
        response.headers["Cache-Control"] = "no-store"
        return await run_in_threadpool(service.extract, data, business_id=business_id)
    finally:
        await form.close()
