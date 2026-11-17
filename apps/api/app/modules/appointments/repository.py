from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.modules.appointments.models import (
    Appointment,
    AppointmentStatus,
    BusinessHour,
)
from app.modules.appointments.schemas import BusinessHourItem
from app.modules.businesses.models import Business
from app.modules.professionals.models import Professional
from app.modules.services.associations import professional_services
from app.modules.services.models import Service


class AppointmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_business(self, business_id: UUID) -> UUID | None:
        # Every agenda writer locks the same row, including business-wide blocks.
        return self.session.scalar(
            select(Business.id).where(Business.id == business_id).with_for_update()
        )

    def has_overlap(
        self,
        *,
        business_id: UUID,
        professional_id: UUID | None,
        starts_at: datetime,
        ends_at: datetime,
    ) -> bool:
        statement = select(Appointment.id).where(
            Appointment.business_id == business_id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at,
        )
        if professional_id is not None:
            statement = statement.where(
                or_(
                    Appointment.professional_id == professional_id,
                    Appointment.professional_id.is_(None),
                )
            )
        return self.session.scalar(statement.limit(1)) is not None

    def list_hours(self, *, business_id: UUID) -> list[BusinessHour]:
        statement = (
            select(BusinessHour)
            .where(BusinessHour.business_id == business_id)
            .order_by(BusinessHour.weekday, BusinessHour.opens_at)
        )
        return list(self.session.scalars(statement).all())

    def replace_hours(
        self, hours: list[BusinessHourItem], *, business_id: UUID
    ) -> list[BusinessHour]:
        self.session.execute(
            delete(BusinessHour).where(BusinessHour.business_id == business_id)
        )
        self.session.add_all(
            BusinessHour(business_id=business_id, **hour.model_dump()) for hour in hours
        )
        self.session.flush()
        return self.list_hours(business_id=business_id)

    def list_active_services(self, *, business_id: UUID) -> list[Service]:
        statement = (
            select(Service)
            .where(Service.business_id == business_id, Service.is_active.is_(True))
            .order_by(Service.name)
        )
        return list(self.session.scalars(statement).all())

    def list_active_professionals(
        self, *, business_id: UUID, service_id: UUID
    ) -> list[Professional]:
        statement = (
            select(Professional)
            .join(
                professional_services,
                professional_services.c.professional_id == Professional.id,
            )
            .where(
                Professional.business_id == business_id,
                Professional.is_active.is_(True),
                professional_services.c.service_id == service_id,
            )
            .order_by(Professional.name)
        )
        return list(self.session.scalars(statement).all())

    def get_bookable_service(
        self, *, business_id: UUID, service_id: UUID, professional_id: UUID
    ) -> Service | None:
        """Active service offered by an active professional of the same business."""
        statement = (
            select(Service)
            .join(
                professional_services,
                professional_services.c.service_id == Service.id,
            )
            .join(
                Professional,
                Professional.id == professional_services.c.professional_id,
            )
            .where(
                Service.id == service_id,
                Service.business_id == business_id,
                Service.is_active.is_(True),
                Professional.id == professional_id,
                Professional.is_active.is_(True),
            )
        )
        return self.session.scalar(statement)

    def list_busy(
        self,
        *,
        business_id: UUID,
        professional_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
    ) -> list[tuple[datetime, datetime]]:
        statement = select(Appointment.starts_at, Appointment.ends_at).where(
            Appointment.business_id == business_id,
            or_(
                Appointment.professional_id == professional_id,
                Appointment.professional_id.is_(None),
            ),
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at,
        )
        return [(row.starts_at, row.ends_at) for row in self.session.execute(statement)]

    def count_future_by_phone(
        self, *, business_id: UUID, phone: str, now: datetime
    ) -> int:
        statement = select(func.count()).where(
            Appointment.business_id == business_id,
            Appointment.customer_phone == phone,
            Appointment.starts_at > now,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        return self.session.scalar(statement) or 0

    def create(self, appointment: Appointment) -> Appointment:
        self.session.add(appointment)
        self.session.flush()
        return appointment

    def get_by_id(
        self, appointment_id: UUID, *, business_id: UUID
    ) -> Appointment | None:
        statement = select(Appointment).where(
            Appointment.id == appointment_id, Appointment.business_id == business_id
        )
        return self.session.scalar(statement)

    def list(
        self,
        *,
        business_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
        professional_id: UUID | None = None,
        service_id: UUID | None = None,
        status: AppointmentStatus | None = None,
        customer_phone: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Appointment]:
        statement = (
            select(Appointment)
            .where(
                Appointment.business_id == business_id,
                Appointment.starts_at < ends_at,
                Appointment.ends_at > starts_at,
            )
            .order_by(Appointment.starts_at, Appointment.id)
            .offset(offset)
        )
        for field_name, value in (
            ("professional_id", professional_id),
            ("service_id", service_id),
            ("status", status),
            ("customer_phone", customer_phone),
        ):
            if value is not None:
                statement = statement.where(getattr(Appointment, field_name) == value)
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement).all())
