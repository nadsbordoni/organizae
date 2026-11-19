from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.admin.schemas import AdminBusinessDetail, AdminBusinessSummary
from app.modules.admin.service import AdminService
from app.modules.auth.dependencies import get_platform_admin
from app.modules.subscriptions.models import SubscriptionStatus

# Everything here is for the platform's own staff.
router = APIRouter(
    prefix="/admin",
    tags=["Platform admin"],
    dependencies=[Depends(get_platform_admin)],
)

MAX_PAGE_SIZE = 100


def get_admin_service(session: Annotated[Session, Depends(get_db)]) -> AdminService:
    return AdminService(session)


ServiceDep = Annotated[AdminService, Depends(get_admin_service)]


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
