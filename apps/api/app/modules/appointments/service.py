from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.appointments.exceptions import (
    AppointmentConflictError,
    AppointmentNotFoundError,
    InvalidBookingError,
)
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    BusinessHour,
)
from app.modules.appointments.notifications import (
    booking_details,
    confirmation_message,
    send_email,
)
from app.modules.appointments.repository import AppointmentRepository
from app.modules.appointments.schemas import (
    AppointmentStatusUpdate,
    AppointmentUpdate,
    BlockCreateRequest,
    BusinessHoursUpdate,
    OnlineBookingRequest,
    RescheduleRequest,
)
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.professionals.models import Professional
from app.modules.services.models import Service

SLOT_INTERVAL = timedelta(minutes=30)
BOOKING_WINDOW = timedelta(days=120)
MAX_LISTING_RANGE = timedelta(days=31)
# Against abuse of the public page: future bookings allowed per phone.
MAX_FUTURE_BOOKINGS_PER_PHONE = 3
EDITABLE_STATUSES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


def build_slots(
    day: date,
    hours: list[tuple[time, time]],
    duration: timedelta,
    busy: list[tuple[datetime, datetime]],
    now: datetime,
    tz: ZoneInfo,
) -> list[datetime]:
    """Free start times of `day` inside the opening windows, every SLOT_INTERVAL."""
    slots = []
    for opens_at, closes_at in hours:
        start = datetime.combine(day, opens_at, tz)
        window_end = datetime.combine(day, closes_at, tz)
        while start + duration <= window_end:
            end = start + duration
            if start > now and not any(s < end and e > start for s, e in busy):
                slots.append(start)
            start += SLOT_INTERVAL
    return sorted(slots)


class AppointmentService:
    def __init__(self, session: Session, tz: ZoneInfo) -> None:
        self.session = session
        self.tz = tz
        self.repository = AppointmentRepository(session)
        self.business_repository = BusinessRepository(session)

    def get_hours(self, *, business_id: UUID) -> list[BusinessHour]:
        return self.repository.list_hours(business_id=business_id)

    def replace_hours(
        self, hours_data: BusinessHoursUpdate, *, business_id: UUID
    ) -> list[BusinessHour]:
        with self._transaction():
            self._lock_business(business_id)
            hours = self.repository.replace_hours(
                hours_data.hours, business_id=business_id
            )
            self.session.commit()
        return hours

    def list_public_services(self, *, business_id: UUID) -> list[Service]:
        self._ensure_business(business_id)
        return self.repository.list_active_services(business_id=business_id)

    def list_public_professionals(
        self, *, business_id: UUID, service_id: UUID
    ) -> list[Professional]:
        self._ensure_business(business_id)
        return self.repository.list_active_professionals(
            business_id=business_id, service_id=service_id
        )

    def get_availability(
        self,
        *,
        business_id: UUID,
        service_id: UUID,
        professional_id: UUID,
        day: date,
        now: datetime | None = None,
    ) -> list[datetime]:
        now = now or datetime.now(UTC)
        self._ensure_business(business_id)
        service = self._get_bookable_service(business_id, service_id, professional_id)
        if day > (now + BOOKING_WINDOW).astimezone(self.tz).date():
            return []
        return self._free_slots(business_id, professional_id, service, day, now)

    def book_online(
        self,
        booking: OnlineBookingRequest,
        *,
        business_id: UUID,
        now: datetime | None = None,
    ) -> Appointment:
        return self._book(
            booking, business_id=business_id, source=AppointmentSource.ONLINE, now=now
        )

    def book_panel(
        self,
        booking: OnlineBookingRequest,
        *,
        business_id: UUID,
        now: datetime | None = None,
    ) -> Appointment:
        return self._book(
            booking, business_id=business_id, source=AppointmentSource.PANEL, now=now
        )

    def _book(
        self,
        booking: OnlineBookingRequest,
        *,
        business_id: UUID,
        source: AppointmentSource,
        now: datetime | None,
    ) -> Appointment:
        with self._transaction():
            self._lock_business(business_id)
            # Re-read rules and availability after waiting for concurrent writers.
            now = now or datetime.now(UTC)
            service = self._get_bookable_service(
                business_id, booking.service_id, booking.professional_id
            )
            starts_at = booking.starts_at.astimezone(self.tz)
            if starts_at > now + BOOKING_WINDOW:
                raise InvalidBookingError("Time is outside the booking window")
            free = self._free_slots(
                business_id, booking.professional_id, service, starts_at.date(), now
            )
            if starts_at not in free:
                raise AppointmentConflictError("This time is no longer available")
            if (
                self.repository.count_future_by_phone(
                    business_id=business_id, phone=booking.customer_phone, now=now
                )
                >= MAX_FUTURE_BOOKINGS_PER_PHONE
            ):
                raise InvalidBookingError(
                    "This phone already has upcoming bookings; contact the business"
                )
            appointment = self.repository.create(
                Appointment(
                    business_id=business_id,
                    professional_id=booking.professional_id,
                    service_id=service.id,
                    customer_name=booking.customer_name,
                    customer_phone=booking.customer_phone,
                    customer_email=booking.customer_email,
                    notes=booking.notes,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=service.duration_minutes),
                    status=AppointmentStatus.PENDING,
                    source=source,
                )
            )
            self.session.commit()
            self.session.refresh(appointment)
        return appointment

    def reschedule_online(
        self,
        appointment_id: UUID,
        data: RescheduleRequest,
        *,
        business_id: UUID,
        now: datetime | None = None,
    ) -> Appointment:
        with self._transaction():
            self._lock_business(business_id)
            now = now or datetime.now(UTC)
            appointment = self.repository.get_by_id(
                appointment_id, business_id=business_id
            )
            # A wrong phone looks like a missing booking: ids must not be probed.
            if appointment is None or appointment.customer_phone != data.customer_phone:
                raise AppointmentNotFoundError("Appointment not found")
            if appointment.status != AppointmentStatus.CONFIRMED:
                raise InvalidBookingError(
                    "Only confirmed appointments can be rescheduled"
                )
            if appointment.starts_at <= now:
                raise InvalidBookingError("Appointment has already started")
            if data.starts_at == appointment.starts_at:
                raise InvalidBookingError("Choose a different time")
            self._move(
                appointment,
                service_id=appointment.service_id,
                professional_id=appointment.professional_id,
                starts_at=data.starts_at,
                now=now,
            )
            self.session.commit()
            self.session.refresh(appointment)
        return appointment

    def get_editable(self, appointment_id: UUID, *, business_id: UUID) -> Appointment:
        appointment = self.repository.get_by_id(appointment_id, business_id=business_id)
        if appointment is None:
            raise AppointmentNotFoundError("Appointment not found")
        if appointment.status not in EDITABLE_STATUSES:
            raise InvalidBookingError(
                "Only pending or confirmed appointments can be changed"
            )
        return appointment

    def check_panel_update(
        self,
        appointment_id: UUID,
        data: AppointmentUpdate,
        *,
        business_id: UUID,
        now: datetime | None = None,
    ) -> Appointment:
        """Validates an edit without writing; update_panel validates again under the lock."""
        appointment = self.get_editable(appointment_id, business_id=business_id)
        target = self._update_target(appointment, data)
        if target is not None:
            self._check_move(appointment, **target, now=now or datetime.now(UTC))
        return appointment

    def update_panel(
        self,
        appointment_id: UUID,
        data: AppointmentUpdate,
        *,
        business_id: UUID,
        now: datetime | None = None,
    ) -> Appointment:
        """Reschedules or edits a booking from the business side; no phone check."""
        with self._transaction():
            self._lock_business(business_id)
            now = now or datetime.now(UTC)
            appointment = self.get_editable(appointment_id, business_id=business_id)
            target = self._update_target(appointment, data)
            if target is not None:
                self._move(appointment, **target, now=now)
            if "notes" in data.model_fields_set:
                appointment.notes = data.notes
            self.session.flush()
            self.session.commit()
            self.session.refresh(appointment)
        return appointment

    def _update_target(
        self, appointment: Appointment, data: AppointmentUpdate
    ) -> dict | None:
        """New service/professional/time, or None when only the notes change."""
        target = {
            "service_id": data.service_id or appointment.service_id,
            "professional_id": data.professional_id or appointment.professional_id,
            "starts_at": data.starts_at or appointment.starts_at,
        }
        if target == {
            "service_id": appointment.service_id,
            "professional_id": appointment.professional_id,
            "starts_at": appointment.starts_at,
        }:
            if "notes" not in data.model_fields_set:
                raise InvalidBookingError("Nothing to change")
            return None
        return target

    def _check_move(
        self,
        appointment: Appointment,
        *,
        service_id: UUID,
        professional_id: UUID,
        starts_at: datetime,
        now: datetime,
    ) -> Service:
        if appointment.starts_at <= now:
            raise InvalidBookingError("Appointment has already started")
        if starts_at > now + BOOKING_WINDOW:
            raise InvalidBookingError("Time is outside the booking window")
        service = self._get_bookable_service(
            appointment.business_id, service_id, professional_id
        )
        free = self._free_slots(
            appointment.business_id,
            professional_id,
            service,
            starts_at.astimezone(self.tz).date(),
            now,
            exclude_appointment_id=appointment.id,
        )
        if starts_at not in free:
            raise AppointmentConflictError("This time is no longer available")
        return service

    def _move(
        self,
        appointment: Appointment,
        *,
        service_id: UUID,
        professional_id: UUID,
        starts_at: datetime,
        now: datetime,
    ) -> None:
        """Moves the booking in place, so the previous time is freed by the same write."""
        service = self._check_move(
            appointment,
            service_id=service_id,
            professional_id=professional_id,
            starts_at=starts_at,
            now=now,
        )
        starts_at = starts_at.astimezone(self.tz)
        appointment.service_id = service.id
        appointment.professional_id = professional_id
        appointment.starts_at = starts_at
        appointment.ends_at = starts_at + timedelta(minutes=service.duration_minutes)
        self.session.flush()

    def list_appointments(
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
        if ends_at <= starts_at or ends_at - starts_at > MAX_LISTING_RANGE:
            raise InvalidBookingError("Range must be positive and at most 31 days")
        if offset < 0 or (limit is not None and not 1 <= limit <= 100):
            raise InvalidBookingError("Invalid appointment pagination")
        return self.repository.list(
            business_id=business_id,
            starts_at=starts_at,
            ends_at=ends_at,
            professional_id=professional_id,
            service_id=service_id,
            status=status,
            customer_phone=customer_phone,
            offset=offset,
            limit=limit,
        )

    def create_block(
        self, block: BlockCreateRequest, *, business_id: UUID
    ) -> Appointment:
        with self._transaction():
            self._lock_business(business_id)
            if self.repository.has_overlap(
                business_id=business_id,
                professional_id=block.professional_id,
                starts_at=block.starts_at,
                ends_at=block.ends_at,
            ):
                raise AppointmentConflictError("Block overlaps an existing appointment")
            appointment = self.repository.create(
                Appointment(
                    business_id=business_id,
                    professional_id=block.professional_id,
                    notes=block.notes,
                    starts_at=block.starts_at,
                    ends_at=block.ends_at,
                    status=AppointmentStatus.BLOCKED,
                    source=AppointmentSource.PANEL,
                )
            )
            self.session.commit()
            self.session.refresh(appointment)
        return appointment

    def update_status(
        self,
        appointment_id: UUID,
        status_data: AppointmentStatusUpdate,
        *,
        business_id: UUID,
    ) -> Appointment:
        with self._transaction():
            self._lock_business(business_id)
            appointment = self.repository.get_by_id(
                appointment_id, business_id=business_id
            )
            if appointment is None:
                raise AppointmentNotFoundError("Appointment not found")
            if appointment.status == AppointmentStatus.CANCELLED:
                raise AppointmentConflictError("Appointment is already cancelled")
            newly_confirmed = (
                status_data.status == AppointmentStatus.CONFIRMED
                and appointment.status != AppointmentStatus.CONFIRMED
            )
            appointment.status = status_data.status
            self.session.flush()
            self.session.commit()
            self.session.refresh(appointment)
        # After the commit: the SMTP call must not hold the business lock.
        if newly_confirmed:
            self._send_confirmation(appointment)
        return appointment

    def _send_confirmation(self, appointment: Appointment) -> None:
        if not (
            appointment.customer_email
            and appointment.customer_name
            and appointment.service_id
            and appointment.professional_id
        ):
            return
        names = self.repository.get_booking_names(
            business_id=appointment.business_id,
            service_id=appointment.service_id,
            professional_id=appointment.professional_id,
        )
        business = self.business_repository.get_by_id(appointment.business_id)
        if names is None or business is None:
            return
        subject, body = confirmation_message(
            customer_name=appointment.customer_name,
            business_name=business.name,
            details=booking_details(
                service_name=names[0],
                professional_name=names[1],
                starts_at=appointment.starts_at,
                tz=self.tz,
            ),
        )
        send_email(appointment.customer_email, subject, body)

    def _free_slots(
        self,
        business_id: UUID,
        professional_id: UUID,
        service: Service,
        day: date,
        now: datetime,
        exclude_appointment_id: UUID | None = None,
    ) -> list[datetime]:
        hours = [
            (hour.opens_at, hour.closes_at)
            for hour in self.repository.list_hours(business_id=business_id)
            if hour.weekday == day.weekday()
        ]
        if not hours:
            return []
        day_start = datetime.combine(day, time.min, self.tz)
        busy = self.repository.list_busy(
            business_id=business_id,
            professional_id=professional_id,
            starts_at=day_start,
            ends_at=day_start + timedelta(days=1),
            exclude_appointment_id=exclude_appointment_id,
        )
        return build_slots(
            day,
            hours,
            timedelta(minutes=service.duration_minutes),
            busy,
            now,
            self.tz,
        )

    def _ensure_business(self, business_id: UUID) -> None:
        if self.business_repository.get_by_id(business_id) is None:
            raise BusinessNotFoundError("Business not found")

    def _lock_business(self, business_id: UUID) -> None:
        if self.repository.lock_business(business_id) is None:
            raise BusinessNotFoundError("Business not found")

    def _get_bookable_service(
        self, business_id: UUID, service_id: UUID, professional_id: UUID
    ) -> Service:
        service = self.repository.get_bookable_service(
            business_id=business_id,
            service_id=service_id,
            professional_id=professional_id,
        )
        if service is None:
            raise InvalidBookingError("Service or professional is not available")
        return service

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            # Includes the overlap exclusion constraint: someone booked first.
            raise AppointmentConflictError(
                "Operation conflicts with another appointment or related data"
            ) from exc
        except Exception:
            self.session.rollback()
            raise
