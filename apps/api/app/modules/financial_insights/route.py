from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.assistant.providers.base import AssistantProvider
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.auth.dependencies import get_current_business_id
from app.modules.financial_insights.explanations import (
    InsightExplainer,
    explanation_cache,
)
from app.modules.financial_insights.schemas import (
    FinancialInsightsQuery,
    FinancialInsightsResponse,
)
from app.modules.financial_insights.service import FinancialInsightsService

router = APIRouter(prefix="/financial/insights", tags=["Financial insights"])


def get_insights_service(
    session: Annotated[Session, Depends(get_db)],
) -> FinancialInsightsService:
    return FinancialInsightsService(session, ZoneInfo(settings.BUSINESS_TIMEZONE))


def get_insights_provider() -> AssistantProvider | None:
    if not settings.GEMINI_API_KEY.get_secret_value().strip():
        return None
    return GeminiProvider(settings)


def get_insight_explainer(
    provider: Annotated[AssistantProvider | None, Depends(get_insights_provider)],
) -> InsightExplainer:
    return InsightExplainer(provider, explanation_cache, settings.GEMINI_MODEL.strip())


def get_insight_clock() -> datetime:
    return datetime.now(UTC)


@router.get(
    "", response_model=FinancialInsightsResponse, response_model_exclude_none=True
)
def financial_insights(
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    query: Annotated[FinancialInsightsQuery, Query()],
    service: Annotated[FinancialInsightsService, Depends(get_insights_service)],
    explainer: Annotated[InsightExplainer, Depends(get_insight_explainer)],
    now: Annotated[datetime, Depends(get_insight_clock)],
) -> FinancialInsightsResponse:
    response = service.analyze(business_id=business_id, month=query.month, now=now)
    return (
        explainer.enrich(response, business_id=business_id)
        if query.explain
        else response
    )
