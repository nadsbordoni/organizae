from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.admin.schemas import (
    AdminBusinessDetail,
    AdminBusinessSummary,
    ExtendTrialRequest,
    PlatformMetrics,
    ReactivateRequest,
)
from app.modules.admin.service import AdminService
from app.modules.auth.dependencies import get_platform_admin
from app.modules.subscriptions.exceptions import (
    InvalidSubscriptionTransitionError,
    SubscriptionError,
    SubscriptionNotFoundError,
)
from app.modules.subscriptions.models import SubscriptionStatus
from app.modules.subscriptions.service import SubscriptionService

# Everything here is for the platform's own staff.
router = APIRouter(
    prefix="/admin",
    tags=["Platform admin"],
    dependencies=[Depends(get_platform_admin)],
)

MAX_PAGE_SIZE = 100


def get_admin_service(session: Annotated[Session, Depends(get_db)]) -> AdminService:
    return AdminService(
        session,
        SubscriptionService(
            session, trial_days=settings.TRIAL_DAYS, grace_days=settings.GRACE_DAYS
        ),
    )


ServiceDep = Annotated[AdminService, Depends(get_admin_service)]


async def subscription_error_handler(
    request: Request, exc: SubscriptionError
) -> JSONResponse:
    details = {
        SubscriptionNotFoundError: (status.HTTP_404_NOT_FOUND, "Subscription not found"),
        InvalidSubscriptionTransitionError: (
            status.HTTP_409_CONFLICT,
            "This action is not allowed for the current subscription status",
        ),
    }
    code, detail = details.get(
        type(exc), (status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")
    )
    return JSONResponse(status_code=code, content={"detail": detail})


@router.get("/metrics", response_model=PlatformMetrics)
def get_metrics(service: ServiceDep):
    return service.metrics()


@router.get("/businesses", response_model=list[AdminBusinessSummary])
def list_businesses(
    service: ServiceDep,
    subscription_status: Annotated[
        SubscriptionStatus | None, Query(alias="status")
    ] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return service.list_businesses(
        status=subscription_status, search=q, limit=limit, offset=offset
    )


@router.get("/businesses/{business_id}", response_model=AdminBusinessDetail)
def get_business(business_id: UUID, service: ServiceDep):
    return service.get_business(business_id)


@router.post("/businesses/{business_id}/extend-trial", response_model=AdminBusinessDetail)
def extend_trial(business_id: UUID, data: ExtendTrialRequest, service: ServiceDep):
    return service.extend_trial(business_id, days=data.days)


@router.post("/businesses/{business_id}/suspend", response_model=AdminBusinessDetail)
def suspend(business_id: UUID, service: ServiceDep):
    return service.suspend(business_id)


@router.post("/businesses/{business_id}/reactivate", response_model=AdminBusinessDetail)
def reactivate(
    business_id: UUID,
    service: ServiceDep,
    data: ReactivateRequest | None = None,
):
    return service.reactivate(business_id, days=(data or ReactivateRequest()).days)


@router.post("/businesses/{business_id}/cancel", response_model=AdminBusinessDetail)
def cancel(business_id: UUID, service: ServiceDep):
    return service.cancel(business_id)
