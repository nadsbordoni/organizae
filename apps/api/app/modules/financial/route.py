from datetime import date
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import UUID4
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_business_id
from app.modules.financial.exceptions import (
    FinancialInsightsUnavailableError,
    FinancialReportError,
    InvalidFinancialReportError,
)
from app.modules.financial.schemas import (
    CashFlowGrouping,
    CashFlowResponse,
    CategoryReportResponse,
    FinancialSummaryResponse,
    ProfitabilityResponse,
)
from app.modules.financial.service import FinancialReportService
from app.modules.financial_categories.models import FinancialType

router = APIRouter(prefix="/financial", tags=["Financial reports"])


def get_financial_report_service(
    session: Annotated[Session, Depends(get_db)],
) -> FinancialReportService:
    return FinancialReportService(session, ZoneInfo(settings.BUSINESS_TIMEZONE))


async def financial_report_error_handler(
    request: Request, exc: FinancialReportError
) -> JSONResponse:
    if isinstance(exc, FinancialInsightsUnavailableError):
        return JSONResponse(
            status_code=503,
            content={
                "code": "financial_insights_unavailable",
                "detail": "Os dados financeiros estão temporariamente indisponíveis.",
            },
        )
    status_code = (
        status.HTTP_422_UNPROCESSABLE_CONTENT
        if isinstance(exc, InvalidFinancialReportError)
        else status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc) if status_code != 500 else "Internal server error"},
    )


CurrentBusinessId = Annotated[UUID, Depends(get_current_business_id)]
FinancialReportServiceDep = Annotated[
    FinancialReportService, Depends(get_financial_report_service)
]


@router.get("/summary", response_model=FinancialSummaryResponse)
def financial_summary(
    business_id: CurrentBusinessId,
    service: FinancialReportServiceDep,
    start_date: date | None = None,
    end_date: date | None = None,
    category_id: UUID4 | None = None,
) -> FinancialSummaryResponse:
    return service.summary(
        business_id=business_id,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
    )


@router.get("/reports/cash-flow", response_model=CashFlowResponse)
def cash_flow_report(
    business_id: CurrentBusinessId,
    service: FinancialReportServiceDep,
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: CashFlowGrouping = CashFlowGrouping.DAY,
    category_id: UUID4 | None = None,
) -> CashFlowResponse:
    return service.cash_flow(
        business_id=business_id,
        start_date=start_date,
        end_date=end_date,
        group_by=group_by,
        category_id=category_id,
    )


@router.get("/reports/categories", response_model=CategoryReportResponse)
def categories_report(
    business_id: CurrentBusinessId,
    service: FinancialReportServiceDep,
    start_date: date | None = None,
    end_date: date | None = None,
    entry_type: Annotated[FinancialType | None, Query(alias="type")] = None,
    category_id: UUID4 | None = None,
) -> CategoryReportResponse:
    return service.categories(
        business_id=business_id,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        entry_type=entry_type,
    )


@router.get("/reports/profitability", response_model=ProfitabilityResponse)
def profitability_report(
    business_id: CurrentBusinessId,
    service: FinancialReportServiceDep,
    start_date: date,
    end_date: date,
) -> ProfitabilityResponse:
    return service.profitability(
        business_id=business_id, start_date=start_date, end_date=end_date
    )
