from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.modules.appointments.models import Appointment
from app.modules.notifications.models import Notification
from app.modules.services.models import Service


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, notification: Notification) -> Notification:
        self.session.add(notification)
        self.session.flush()
        return notification

    def list(
        self, *, business_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[tuple[Notification, Appointment, str]]:
        """Newest first, with the appointment and the name of its service."""
        statement = (
            select(Notification, Appointment, Service.name)
            .join(
                Appointment,
                and_(
                    Appointment.id == Notification.appointment_id,
                    Appointment.business_id == Notification.business_id,
                ),
            )
            .join(
                Service,
                and_(
                    Service.id == Appointment.service_id,
                    Service.business_id == Appointment.business_id,
                ),
            )
            .where(Notification.business_id == business_id)
            .order_by(Notification.created_at.desc(), Notification.id)
            .offset(offset)
            .limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in self.session.execute(statement).all()]
