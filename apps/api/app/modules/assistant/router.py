from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.modules.assistant.exceptions import (
    AssistantError,
    AssistantInvalidResponseError,
    AssistantRateLimitError,
    AssistantTimeoutError,
    AssistantUnavailableError,
)
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.assistant.schemas import ChatRequest, ChatResponse
from app.modules.assistant.service import AssistantProvider, AssistantService

router = APIRouter(prefix="/assistant", tags=["Assistant"])


def get_assistant_provider() -> AssistantProvider:
    return GeminiProvider(settings)


def get_assistant_service(
    provider: Annotated[AssistantProvider, Depends(get_assistant_provider)],
) -> AssistantService:
    return AssistantService(provider)


async def assistant_error_handler(
    request: Request, exc: AssistantError
) -> JSONResponse:
    status_codes = {
        AssistantTimeoutError: 504,
        AssistantRateLimitError: 429,
        AssistantUnavailableError: 503,
        AssistantInvalidResponseError: 502,
    }
    code = next(
        (value for error, value in status_codes.items() if isinstance(exc, error)),
        500,
    )
    return JSONResponse(
        status_code=code,
        content={"detail": exc.public_message, "code": exc.code},
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    data: ChatRequest,
    service: Annotated[AssistantService, Depends(get_assistant_service)],
) -> ChatResponse:
    return service.chat(data)
