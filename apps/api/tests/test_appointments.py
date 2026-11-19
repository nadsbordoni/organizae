from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.main import app
    from app.modules.appointments.route import get_appointment_service

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
from app.modules.appointments.repository import AppointmentRepository
from app.modules.appointments.schemas import (
    BusinessHoursUpdate,
    OnlineBookingRequest,
    RescheduleRequest,
)
from app.modules.appointments.service import AppointmentService, build_slots
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.services.models import Service

tz = ZoneInfo("America/Sao_Paulo")
business_id = uuid4()
service_id = uuid4()
professional_id = uuid4()
monday = date(2026, 11, 9)
now = datetime(2026, 11, 4, 12, 0, tzinfo=tz)
# Monday to Thursday 08-12 and 14-18, like the original clinic.
hours = [
    BusinessHour(business_id=business_id, weekday=weekday, opens_at=opens, closes_at=closes)
    for weekday in range(4)
    for opens, closes in ((time(8), time(12)), (time(14), time(18)))
]


def at(hour: int, minute: int = 0, day: date = monday) -> datetime:
    return datetime.combine(day, time(hour, minute), tz)


def test_build_slots_respects_windows_duration_and_busy() -> None:
    slots = build_slots(
        monday,
        [(time(8), time(12)), (time(14), time(15))],
        timedelta(minutes=60),
        busy=[(at(9), at(9, 30))],
        now=now,
        tz=tz,
    )
    assert slots == [at(8), at(9, 30), at(10), at(10, 30), at(11), at(14)]


def test_build_slots_skips_past_times() -> None:
    slots = build_slots(
        monday, [(time(8), time(10))], timedelta(minutes=30), [], at(9), tz
    )
    assert slots == [at(9, 30)]


def test_booking_request_normalizes_phone() -> None:
    booking = OnlineBookingRequest(
        service_id=service_id,
        professional_id=professional_id,
        starts_at=at(8),
        customer_name="  Maria Silva ",
        customer_phone="(81) 98757-0102",
    )
    assert booking.customer_phone == "81987570102"
    assert booking.customer_name == "Maria Silva"
    with pytest.raises(ValidationError):
        OnlineBookingRequest(**{**booking.model_dump(), "customer_phone": "1234"})


def test_business_hours_reject_overlap() -> None:
    with pytest.raises(ValidationError):
        BusinessHoursUpdate(
            hours=[
                {"weekday": 0, "opens_at": "08:00", "closes_at": "12:00"},
                {"weekday": 0, "opens_at": "11:00", "closes_at": "13:00"},
            ]
        )


@pytest.fixture
def service() -> AppointmentService:
    appointment_service = AppointmentService(Mock(spec=Session), tz)
    appointment_service.repository = Mock(spec=AppointmentRepository)
    appointment_service.business_repository = Mock(spec=BusinessRepository)
    appointment_service.repository.list_hours.return_value = hours
    appointment_service.repository.list_busy.return_value = [(at(8), at(8, 30))]
    appointment_service.repository.get_bookable_service.return_value = Service(
        id=service_id, business_id=business_id, duration_minutes=30
    )
    appointment_service.repository.count_future_by_phone.return_value = 0
    appointment_service.repository.lock_business.return_value = business_id
    appointment_service.repository.has_overlap.return_value = False
    appointment_service.repository.create.side_effect = lambda appointment: appointment
    return appointment_service


def booking_at(starts_at: datetime) -> OnlineBookingRequest:
    return OnlineBookingRequest(
        service_id=service_id,
        professional_id=professional_id,
        starts_at=starts_at,
        customer_name="Maria Silva",
        customer_phone="81987570102",
    )


def test_availability_lists_free_slots(service: AppointmentService) -> None:
    slots = service.get_availability(
        business_id=business_id,
        service_id=service_id,
        professional_id=professional_id,
        day=monday,
        now=now,
    )
    assert slots[0] == at(8, 30)
    assert at(12) not in slots and at(14) in slots and slots[-1] == at(17, 30)
    assert len(slots) == 15


def test_availability_is_empty_on_closed_day(service: AppointmentService) -> None:
    saturday = monday + timedelta(days=5)
    assert (
        service.get_availability(
            business_id=business_id,
            service_id=service_id,
            professional_id=professional_id,
            day=saturday,
            now=now,
        )
        == []
    )


def test_book_online_creates_pending_appointment(service: AppointmentService) -> None:
    appointment = service.book_online(
        booking_at(at(9).astimezone(ZoneInfo("UTC"))), business_id=business_id, now=now
    )
    assert appointment.starts_at == at(9)
    assert appointment.ends_at == at(9, 30)
    assert appointment.status == AppointmentStatus.PENDING
    assert appointment.source == AppointmentSource.ONLINE
    service.session.commit.assert_called_once_with()


@pytest.mark.parametrize("starts_at", [at(8), at(12), at(9, 15), at(7, 30)])
def test_book_online_rejects_unavailable_time(
    service: AppointmentService, starts_at: datetime
) -> None:
    with pytest.raises(AppointmentConflictError):
        service.book_online(booking_at(starts_at), business_id=business_id, now=now)
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_book_online_limits_future_bookings_per_phone(
    service: AppointmentService,
) -> None:
    service.repository.count_future_by_phone.return_value = 3
    with pytest.raises(InvalidBookingError):
        service.book_online(booking_at(at(9)), business_id=business_id, now=now)
    service.repository.create.assert_not_called()


def test_book_online_rejects_service_not_offered(service: AppointmentService) -> None:
    service.repository.get_bookable_service.return_value = None
    with pytest.raises(InvalidBookingError):
        service.book_online(booking_at(at(9)), business_id=business_id, now=now)


def test_book_online_rejects_unknown_business(service: AppointmentService) -> None:
    service.business_repository.get_by_id.return_value = None
    service.repository.lock_business.return_value = None
    with pytest.raises(BusinessNotFoundError):
        service.book_online(booking_at(at(9)), business_id=business_id, now=now)


def test_book_online_maps_overlap_constraint_to_conflict(
    service: AppointmentService,
) -> None:
    service.repository.create.side_effect = IntegrityError("insert", {}, Exception())
    with pytest.raises(AppointmentConflictError):
        service.book_online(booking_at(at(9)), business_id=business_id, now=now)
    service.session.rollback.assert_called_once_with()


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, Mock]]:
    appointment_service = Mock(spec=AppointmentService)
    app.dependency_overrides[get_appointment_service] = lambda: appointment_service
    try:
        with TestClient(app) as client:
            yield client, appointment_service
    finally:
        app.dependency_overrides.pop(get_appointment_service)


public_path = f"/api/v1/public/businesses/{business_id}"


def test_public_booking_needs_no_auth(api_client: tuple[TestClient, Mock]) -> None:
    client, appointment_service = api_client
    appointment_service.book_online.return_value = Appointment(
        id=uuid4(),
        starts_at=at(9),
        ends_at=at(9, 30),
        status=AppointmentStatus.PENDING,
    )
    response = client.post(
        f"{public_path}/appointments",
        json={
            "service_id": str(service_id),
            "professional_id": str(professional_id),
            "starts_at": at(9).isoformat(),
            "customer_name": "Maria Silva",
            "customer_phone": "(81) 98757-0102",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    assert "customer_phone" not in response.json()


def test_public_booking_conflict_returns_409(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, appointment_service = api_client
    appointment_service.book_online.side_effect = AppointmentConflictError(
        "This time is no longer available"
    )
    response = client.post(
        f"{public_path}/appointments",
        json={
            "service_id": str(service_id),
            "professional_id": str(professional_id),
            "starts_at": at(9).isoformat(),
            "customer_name": "Maria Silva",
            "customer_phone": "81987570102",
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "This time is no longer available"}


def test_public_services_list(api_client: tuple[TestClient, Mock]) -> None:
    client, appointment_service = api_client
    appointment_service.list_public_services.return_value = [
        Service(
            id=service_id,
            business_id=business_id,
            name="Corte",
            description=None,
            price=Decimal("50.00"),
            duration_minutes=30,
        )
    ]
    response = client.get(f"{public_path}/services")
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Corte"


def test_panel_routes_require_auth(api_client: tuple[TestClient, Mock]) -> None:
    client, _ = api_client
    assert client.get("/api/v1/business-hours").status_code == 401
    assert (
        client.get(
            "/api/v1/appointments",
            params={"starts_at": at(0).isoformat(), "ends_at": at(23).isoformat()},
        ).status_code
        == 401
    )


def test_migration_is_in_history_and_postgresql_sql_is_valid() -> None:
    from io import StringIO
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("b3d91f7a2c45")
    assert revision.revision in {
        item.revision
        for item in script.iterate_revisions("head", revision.down_revision)
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in sql
    assert "CREATE TABLE business_hours" in sql and "CREATE TABLE appointments" in sql
    assert "EXCLUDE USING gist" in sql
    assert "DROP" not in sql


PHONE = "81987570102"


def confirmed_at(starts_at: datetime, **overrides: object) -> Appointment:
    values = {
        "id": uuid4(),
        "business_id": business_id,
        "professional_id": professional_id,
        "service_id": service_id,
        "customer_name": "Maria Silva",
        "customer_phone": PHONE,
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(minutes=30),
        "status": AppointmentStatus.CONFIRMED,
        "source": AppointmentSource.ONLINE,
    }
    return Appointment(**{**values, **overrides})


def reschedule(
    service: AppointmentService,
    appointment: Appointment | None,
    starts_at: datetime,
    phone: str = PHONE,
) -> Appointment:
    service.repository.get_by_id.return_value = appointment
    return service.reschedule_online(
        appointment.id if appointment else uuid4(),
        RescheduleRequest(starts_at=starts_at, customer_phone=phone),
        business_id=business_id,
        now=now,
    )


def test_reschedule_moves_the_booking_and_frees_the_old_time(
    service: AppointmentService,
) -> None:
    appointment = confirmed_at(at(10))
    moved = reschedule(service, appointment, at(15).astimezone(ZoneInfo("UTC")))
    assert moved is appointment
    assert (moved.starts_at, moved.ends_at) == (at(15), at(15, 30))
    assert moved.status == AppointmentStatus.CONFIRMED
    # One row is updated in place: the old interval no longer exists.
    service.repository.create.assert_not_called()
    service.session.commit.assert_called_once_with()
    # The booking must not collide with itself when moving by less than its length.
    busy_call = service.repository.list_busy.call_args
    assert busy_call.kwargs["exclude_appointment_id"] == appointment.id


def test_reschedule_rejects_a_time_taken_by_someone_else(
    service: AppointmentService,
) -> None:
    appointment = confirmed_at(at(10))
    # The fixture marks 08:00-08:30 as busy.
    with pytest.raises(AppointmentConflictError):
        reschedule(service, appointment, at(8))
    assert appointment.starts_at == at(10)
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_reschedule_maps_overlap_constraint_to_conflict(
    service: AppointmentService,
) -> None:
    service.session.flush.side_effect = IntegrityError("update", {}, Exception())
    with pytest.raises(AppointmentConflictError):
        reschedule(service, confirmed_at(at(10)), at(15))
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize(
    "overrides, starts_at",
    [
        ({"status": AppointmentStatus.PENDING}, at(15)),
        ({"status": AppointmentStatus.CANCELLED}, at(15)),
        ({"starts_at": now - timedelta(hours=1)}, at(15)),
        ({}, at(10)),
        ({}, at(9, 15)),
        ({}, now + timedelta(days=121)),
    ],
    ids=["pending", "cancelled", "already-started", "same-time", "off-slot", "too-far"],
)
def test_reschedule_rejects_invalid_requests(
    service: AppointmentService, overrides: dict, starts_at: datetime
) -> None:
    base = at(10)
    appointment = confirmed_at(overrides.pop("starts_at", base), **overrides)
    expected = AppointmentConflictError if starts_at == at(9, 15) else InvalidBookingError
    with pytest.raises(expected):
        reschedule(service, appointment, starts_at)
    service.session.commit.assert_not_called()


def test_reschedule_hides_bookings_of_other_customers(
    service: AppointmentService,
) -> None:
    with pytest.raises(AppointmentNotFoundError):
        reschedule(service, confirmed_at(at(10)), at(15), phone="81911112222")
    with pytest.raises(AppointmentNotFoundError):
        reschedule(service, None, at(15))
    service.session.commit.assert_not_called()


def test_public_reschedule_needs_no_auth_and_hides_contact_data(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, appointment_service = api_client
    appointment_id = uuid4()
    appointment_service.reschedule_online.return_value = confirmed_at(
        at(15), id=appointment_id
    )
    response = client.patch(
        f"{public_path}/appointments/{appointment_id}/reschedule",
        json={"starts_at": at(15).isoformat(), "customer_phone": "(81) 98757-0102"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMED"
    assert "customer_phone" not in response.json()
    request = appointment_service.reschedule_online.call_args.args[1]
    assert request.customer_phone == PHONE


@pytest.mark.parametrize(
    "error, status_code",
    [
        (AppointmentNotFoundError("Appointment not found"), 404),
        (AppointmentConflictError("This time is no longer available"), 409),
        (InvalidBookingError("Only confirmed appointments can be rescheduled"), 422),
    ],
)
def test_public_reschedule_error_codes(
    api_client: tuple[TestClient, Mock], error: Exception, status_code: int
) -> None:
    client, appointment_service = api_client
    appointment_service.reschedule_online.side_effect = error
    response = client.patch(
        f"{public_path}/appointments/{uuid4()}/reschedule",
        json={"starts_at": at(15).isoformat(), "customer_phone": PHONE},
    )
    assert response.status_code == status_code
    assert response.json() == {"detail": str(error)}
