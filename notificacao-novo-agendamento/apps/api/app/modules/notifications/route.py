from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_business_id
from app.modules.notifications.schemas import NotificationResponse
from app.modules.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def get_notification_service(
    session: Annotated[Session, Depends(get_db)],
) -> NotificationService:
    return NotificationService(session)


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    business_id: Annotated[UUID, Depends(get_current_business_id)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[NotificationResponse]:
    return service.list(business_id=business_id, offset=offset, limit=limit)
