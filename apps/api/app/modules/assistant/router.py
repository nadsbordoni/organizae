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
    AssistantBusinessNotFoundError,
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
from app.modules.auth.dependencies import get_current_business_id, get_current_user
from app.modules.businesses.service import BusinessService
from app.modules.professionals.service import ProfessionalService
from app.modules.services.service import ServiceService
from app.modules.users.models import User

router = APIRouter(
    prefix="/assistant",
    tags=["Assistant"],
    dependencies=[Depends(get_current_business_id)],
)


def get_assistant_provider() -> AssistantProvider:
    return GeminiProvider(settings)


def get_assistant_tools(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    business_id: Annotated[UUID, Depends(get_current_business_id)],
) -> AssistantTools:
    return AssistantTools(
        business_id,
        BusinessService(session),
        ProfessionalService(session),
        ServiceService(session),
        user_id=current_user.id,
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
        AssistantBusinessNotFoundError: 404,
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
