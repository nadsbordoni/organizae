from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import (
    NotificationAppointment,
    NotificationResponse,
)


class NotificationService:
    def __init__(self, session: Session) -> None:
        self.repository = NotificationRepository(session)

    def list(
        self, *, business_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[NotificationResponse]:
        rows = self.repository.list(
            business_id=business_id, offset=offset, limit=limit
        )
        return [
            NotificationResponse(
                id=notification.id,
                kind=notification.kind,
                read=notification.read_at is not None,
                created_at=notification.created_at,
                appointment=NotificationAppointment(
                    id=appointment.id,
                    status=appointment.status,
                    starts_at=appointment.starts_at,
                    ends_at=appointment.ends_at,
                    customer_name=appointment.customer_name,
                    service_name=service_name,
                ),
            )
            for notification, appointment, service_name in rows
        ]
