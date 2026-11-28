from datetime import datetime

from pydantic import UUID4, BaseModel

from app.modules.appointments.models import AppointmentStatus
from app.modules.notifications.models import NotificationKind


class NotificationAppointment(BaseModel):
    id: UUID4
    status: AppointmentStatus
    starts_at: datetime
    ends_at: datetime
    customer_name: str
    service_name: str


class NotificationResponse(BaseModel):
    id: UUID4
    kind: NotificationKind
    read: bool
    created_at: datetime
    appointment: NotificationAppointment
