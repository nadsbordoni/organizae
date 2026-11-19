from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.subscriptions.service import AccessLevel, SubscriptionService
from app.modules.users.models import User

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_subscription_service(
    session: Annotated[Session, Depends(get_db)],
) -> SubscriptionService:
    return SubscriptionService(
        session, trial_days=settings.TRIAL_DAYS, grace_days=settings.GRACE_DAYS
    )


SubscriptionServiceDep = Annotated[SubscriptionService, Depends(get_subscription_service)]


def check_access(
    service: SubscriptionService, business_id: UUID, *, writing: bool
) -> None:
    """Refuses with 402 when the business may not do this to its data.

    A suspended business can still read; a canceled one cannot even do that.
    A business with no subscription row is not blocked.
    """
    subscription = service.repository.get_by_business_id(business_id)
    level = service.access_level(subscription, now=datetime.now(UTC))
    if level is AccessLevel.NONE:
        detail = "SUBSCRIPTION_CANCELED"
    elif level is AccessLevel.READ_ONLY and writing:
        detail = "SUBSCRIPTION_SUSPENDED"
    else:
        return
    raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, detail=detail)


def require_write_access(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: SubscriptionServiceDep,
) -> None:
    """Router-level guard for the authenticated routes of a business."""
    if current_user.business_id is None:
        return
    check_access(
        service,
        current_user.business_id,
        writing=request.method not in SAFE_METHODS,
    )


def require_public_booking_open(
    request: Request, business_id: UUID, service: SubscriptionServiceDep
) -> None:
    """Router-level guard for the public booking page: only writes are refused."""
    if request.method in SAFE_METHODS:
        return
    check_access(service, business_id, writing=True)
