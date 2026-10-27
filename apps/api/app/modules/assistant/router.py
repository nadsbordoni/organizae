from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.assistant.actions import ActionDecision
from app.modules.assistant.exceptions import (
    AssistantActionStateError,
    AssistantDemoBusinessNotFoundError,
    AssistantDemoConfigurationError,
    AssistantError,
    AssistantInvalidResponseError,
    AssistantRateLimitError,
    AssistantRequestConflictError,
    AssistantTimeoutError,
    AssistantToolCallError,
    AssistantToolLimitError,
    AssistantUnavailableError,
    AssistantWriteBusinessError,
    AssistantWriteDisabledError,
)
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.assistant.schemas import ChatRequest, ChatResponse
from app.modules.assistant.service import AssistantProvider, AssistantService
from app.modules.assistant.tools import AssistantTools
from app.modules.businesses.service import BusinessService
from app.modules.professionals.service import ProfessionalService
from app.modules.services.service import ServiceService

router = APIRouter(prefix="/assistant", tags=["Assistant"])


def get_assistant_provider() -> AssistantProvider:
    return GeminiProvider(settings)


def get_assistant_tools(
    session: Annotated[Session, Depends(get_db)],
) -> AssistantTools | None:
    if not settings.ASSISTANT_DEMO_ENABLED:
        return None
    if (
        settings.APP_ENV not in ("development", "test")
        or not settings.ASSISTANT_DEMO_BUSINESS_ID
    ):
        raise AssistantDemoConfigurationError()
    return AssistantTools(
        settings.ASSISTANT_DEMO_BUSINESS_ID,
        BusinessService(session),
        ProfessionalService(session),
        ServiceService(session),
    )


def get_assistant_service(
    provider: Annotated[AssistantProvider, Depends(get_assistant_provider)],
    tools: Annotated[AssistantTools | None, Depends(get_assistant_tools)],
) -> AssistantService:
    return AssistantService(provider, tools)


async def assistant_error_handler(
    request: Request, exc: AssistantError
) -> JSONResponse:
    status_codes = {
        AssistantDemoBusinessNotFoundError: 404,
        AssistantActionStateError: 409,
        AssistantRequestConflictError: 409,
        AssistantWriteDisabledError: 403,
        AssistantWriteBusinessError: 422,
        AssistantToolCallError: 502,
        AssistantToolLimitError: 502,
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


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
def chat(
    data: ChatRequest,
    service: Annotated[AssistantService, Depends(get_assistant_service)],
) -> ChatResponse:
    return service.chat(data)


@router.post("/actions/{action_id}/confirm")
def confirm_action(
    action_id: UUID,
    data: ActionDecision,
    service: Annotated[AssistantService, Depends(get_assistant_service)],
) -> dict:
    return service.decide_action(action_id, data)


@router.post("/actions/{action_id}/cancel")
def cancel_action(
    action_id: UUID,
    service: Annotated[AssistantService, Depends(get_assistant_service)],
) -> dict:
    return service.decide_action(action_id, ActionDecision(decision="cancel"))
