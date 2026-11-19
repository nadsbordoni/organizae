import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import Session

from app.db.base import Base
from app.modules.appointments.exceptions import AppointmentConflictError
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    BusinessHour,
)
from app.modules.appointments.schemas import (
    AppointmentStatusUpdate,
    BlockCreateRequest,
    OnlineBookingRequest,
    RescheduleRequest,
)
from app.modules.appointments.service import AppointmentService
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.models import Professional
from app.modules.services.associations import professional_services
from app.modules.services.models import Service


@pytest.fixture
def postgres_agenda():
    """Explicit opt-in; all objects are confined to a disposable test schema."""
    dsn = os.environ.get("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("Configure TEST_POSTGRES_URL for real PostgreSQL concurrency tests")
    url = make_url(dsn)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "organizae_test"
    ):
        pytest.fail(
            "TEST_POSTGRES_URL must use a dedicated organizae_test* PostgreSQL database"
        )
    engine = create_engine(url, pool_size=4, max_overflow=0)
    schema = f"assistant_agenda_test_{uuid4().hex}"
    with engine.begin() as connection:
        # btree_gist is installed by the existing appointments migration.
        if not connection.scalar(
            text(
                "SELECT EXISTS (SELECT FROM pg_extension WHERE extname = 'btree_gist')"
            )
        ):
            pytest.fail(
                "Install btree_gist in the disposable test database before running this suite"
            )
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine.dispose()

    @event.listens_for(engine, "connect")
    def set_test_schema(connection, record):
        # Startup options avoid sharing production tables or session-local state.
        previous = connection.autocommit
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}", public')
            cursor.execute("SET statement_timeout = '10s'")
            cursor.execute("SET lock_timeout = '5s'")
        connection.autocommit = previous

    business_id, service_id, professional_id, other_professional = [
        uuid4() for _ in range(4)
    ]
    start = datetime.combine(
        datetime.now(UTC).date() + timedelta(days=2), time(10), UTC
    )
    try:
        with engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                table.create(connection, checkfirst=False)
            connection.execute(
                text(
                    "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_professional_overlap "
                    "EXCLUDE USING gist (professional_id WITH =, tstzrange(starts_at, ends_at) WITH &&) "
                    "WHERE (status <> 'CANCELLED')"
                )
            )
        with Session(engine) as session:
            session.add(BusinessCategory(id=1, name="Test"))
            session.flush()
            session.add(
                Business(
                    id=business_id,
                    category_id=1,
                    name="Test",
                    whatsapp="85999999999",
                    service_mode=ServiceMode.PRESENCIAL,
                )
            )
            session.flush()
            session.add(
                Service(
                    id=service_id,
                    business_id=business_id,
                    name="Test",
                    price=10,
                    duration_minutes=30,
                )
            )
            session.add_all(
                Professional(id=identifier, business_id=business_id, name="Test")
                for identifier in (professional_id, other_professional)
            )
            session.add(
                BusinessHour(
                    business_id=business_id,
                    weekday=start.weekday(),
                    opens_at=time(9),
                    closes_at=time(12),
                )
            )
            session.flush()
            session.execute(
                insert(professional_services),
                [
                    {
                        "business_id": business_id,
                        "service_id": service_id,
                        "professional_id": identifier,
                    }
                    for identifier in (professional_id, other_professional)
                ],
            )
            session.commit()
        yield (
            engine,
            business_id,
            service_id,
            professional_id,
            other_professional,
            start,
        )
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.parametrize(
    "first,second",
    [
        ("panel", "panel"),
        ("online", "panel"),
        ("general_block", "panel"),
        ("panel", "general_block"),
        ("professional_block", "panel"),
        ("panel", "professional_block"),
    ],
)
def test_postgresql_serializes_booking_and_block_creation(
    postgres_agenda, first, second
):
    engine, business_id, service_id, professional_id, _, start = postgres_agenda
    first_holds_lock, release_first, second_attempts_lock = Event(), Event(), Event()
    second_pid = []

    def write(operation, is_first):
        with Session(engine) as session:
            service = AppointmentService(session, ZoneInfo("UTC"))
            lock = service.repository.lock_business

            def controlled_lock(identifier):
                if not is_first:
                    second_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                    second_attempts_lock.set()
                result = lock(identifier)
                if is_first:
                    first_holds_lock.set()
                    assert release_first.wait(5), "Second writer did not reach the lock"
                return result

            service.repository.lock_business = controlled_lock
            try:
                if operation.endswith("block"):
                    service.create_block(
                        BlockCreateRequest(
                            professional_id=professional_id
                            if operation == "professional_block"
                            else None,
                            starts_at=start,
                            ends_at=start + timedelta(minutes=30),
                        ),
                        business_id=business_id,
                    )
                else:
                    method = (
                        service.book_online
                        if operation == "online"
                        else service.book_panel
                    )
                    method(
                        OnlineBookingRequest(
                            service_id=service_id,
                            professional_id=professional_id,
                            starts_at=start,
                            customer_name="Customer",
                            customer_phone="85999999999",
                        ),
                        business_id=business_id,
                    )
                return "created"
            except AppointmentConflictError:
                assert not session.in_transaction()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(write, first, True)
        try:
            assert first_holds_lock.wait(5), (
                "First writer did not acquire the database lock"
            )
            loser = executor.submit(write, second, False)
            assert second_attempts_lock.wait(5)
            # Prove the second connection actually waits on PostgreSQL's lock.
            with engine.connect() as connection:
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    waiting = connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE pid = :pid AND wait_event_type = 'Lock'"
                        ),
                        {"pid": second_pid[0]},
                    )
                    connection.rollback()
                    if waiting:
                        break
                    sleep(0.01)
                assert waiting == 1, "Second writer never waited on the database lock"
        finally:
            release_first.set()
        assert winner.result(timeout=10) == "created"
        assert loser.result(timeout=10) == "conflict"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1


def test_postgresql_allows_parallel_times_for_different_professionals(postgres_agenda):
    engine, business_id, service_id, professional_id, other_professional, start = (
        postgres_agenda
    )

    def book(identifier):
        with Session(engine) as session:
            return (
                AppointmentService(session, ZoneInfo("UTC"))
                .book_panel(
                    OnlineBookingRequest(
                        service_id=service_id,
                        professional_id=identifier,
                        starts_at=start,
                        customer_name="Customer",
                        customer_phone="85999999999",
                    ),
                    business_id=business_id,
                )
                .id
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(book, (professional_id, other_professional)))
    assert len(set(results)) == 2


def test_postgresql_reschedule_frees_old_time_and_ignores_own_interval(postgres_agenda):
    engine, business_id, _, professional_id, _, start = postgres_agenda
    long_service = uuid4()
    with Session(engine) as session:
        session.add(
            Service(
                id=long_service,
                business_id=business_id,
                name="Long",
                price=10,
                duration_minutes=60,
            )
        )
        session.flush()
        session.execute(
            insert(professional_services),
            [
                {
                    "business_id": business_id,
                    "service_id": long_service,
                    "professional_id": professional_id,
                }
            ],
        )
        session.commit()

    def booking(service_id, starts_at, phone):
        return OnlineBookingRequest(
            service_id=service_id,
            professional_id=professional_id,
            starts_at=starts_at,
            customer_name="Customer",
            customer_phone=phone,
        )

    with Session(engine) as session:
        service = AppointmentService(session, ZoneInfo("UTC"))
        mine = service.book_online(
            booking(long_service, start, "85999999999"), business_id=business_id
        )
        mine_id = mine.id
        service.update_status(
            mine_id,
            AppointmentStatusUpdate(status=AppointmentStatus.CONFIRMED),
            business_id=business_id,
        )
        # 10:00-11:00 -> 10:30-11:30 overlaps the booking's own old interval.
        moved = service.reschedule_online(
            mine_id,
            RescheduleRequest(
                starts_at=start + timedelta(minutes=30), customer_phone="85999999999"
            ),
            business_id=business_id,
        )
        assert moved.starts_at == start + timedelta(minutes=30)
        assert moved.ends_at == start + timedelta(minutes=90)

        # The freed 10:00 slot can be booked by someone else...
        service.book_online(
            booking(long_service, start - timedelta(minutes=30), "85988888888"),
            business_id=business_id,
        )
        # ...but a time taken by another booking is still refused, and nothing moves.
        with pytest.raises(AppointmentConflictError):
            service.reschedule_online(
                mine_id,
                RescheduleRequest(
                    starts_at=start - timedelta(minutes=30),
                    customer_phone="85999999999",
                ),
                business_id=business_id,
            )
    with Session(engine) as session:
        assert session.get(Appointment, mine_id).starts_at == start + timedelta(
            minutes=30
        )
        assert session.scalar(select(func.count()).select_from(Appointment)) == 2


def test_postgresql_confirmation_email_names_service_and_professional(postgres_agenda):
    engine, business_id, service_id, professional_id, _, start = postgres_agenda
    with Session(engine) as session:
        service = AppointmentService(session, ZoneInfo("UTC"))
        booked = service.book_online(
            OnlineBookingRequest(
                service_id=service_id,
                professional_id=professional_id,
                starts_at=start,
                customer_name="Maria Silva",
                customer_phone="85999999999",
                customer_email="maria@example.com",
            ),
            business_id=business_id,
        )
        with (
            patch("app.modules.appointments.service.send_email") as send_email,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", SAWarning)  # e.g. a cartesian product
            service.update_status(
                booked.id,
                AppointmentStatusUpdate(status=AppointmentStatus.CONFIRMED),
                business_id=business_id,
            )
    to, _, body = send_email.call_args.args
    assert to == "maria@example.com"
    assert "Serviço: Test" in body and "Profissional: Test" in body
    assert f"Horário: {start:%H:%M}" in body


def _booking(business_id, service_id, professional_id, starts_at, **overrides):
    return Appointment(
        **{
            "business_id": business_id,
            "professional_id": professional_id,
            "service_id": service_id,
            "customer_name": "Maria Silva",
            "customer_phone": "85999999999",
            "customer_email": "maria@example.com",
            "starts_at": starts_at,
            "ends_at": starts_at + timedelta(minutes=30),
            "status": AppointmentStatus.CONFIRMED,
            "source": AppointmentSource.PANEL,
            **overrides,
        }
    )


def test_postgresql_reminders_pick_only_due_bookings_and_only_once(postgres_agenda):
    engine, business_id, service_id, professional_id, other, start = postgres_agenda
    now = start - timedelta(hours=3)
    hour = timedelta(hours=1)
    with Session(engine) as session:
        due = _booking(business_id, service_id, professional_id, start)
        session.add_all(
            [
                due,
                _booking(business_id, service_id, professional_id, start + 3 * 24 * hour),
                _booking(business_id, service_id, other, start, customer_email=None),
                _booking(
                    business_id, service_id, other, start + hour,
                    status=AppointmentStatus.PENDING,
                ),
                _booking(
                    business_id, service_id, professional_id, start + hour,
                    reminder_sent_at=now,
                ),
                _booking(
                    business_id, service_id, professional_id, start + 2 * hour,
                    status=AppointmentStatus.CANCELLED,
                ),
                _booking(business_id, service_id, other, now - hour),
            ]
        )
        session.commit()
        due_id = due.id

    def run():
        with patch(
            "app.modules.appointments.service.send_email", return_value=True
        ) as send_email, Session(engine) as session:
            service = AppointmentService(session, ZoneInfo("UTC"))
            sent = service.send_due_reminders(lead_time=timedelta(hours=24), now=now)
        return sent, send_email

    sent, send_email = run()
    assert sent == 1
    to, subject, body = send_email.call_args.args
    assert to == "maria@example.com" and "Lembrete" in subject
    assert "Serviço: Test" in body and f"Horário: {start:%H:%M}" in body
    with Session(engine) as session:
        assert session.get(Appointment, due_id).reminder_sent_at == now
    assert run()[0] == 0


def test_postgresql_reminder_job_skips_rows_locked_by_another_run(postgres_agenda):
    engine, business_id, service_id, professional_id, _, start = postgres_agenda
    now = start - timedelta(hours=3)
    with Session(engine) as session:
        due = _booking(business_id, service_id, professional_id, start)
        session.add(due)
        session.commit()
        due_id = due.id

    def run():
        with patch(
            "app.modules.appointments.service.send_email", return_value=True
        ), Session(engine) as session:
            service = AppointmentService(session, ZoneInfo("UTC"))
            return service.send_due_reminders(lead_time=timedelta(hours=24), now=now)

    with Session(engine) as other_run:
        other_run.execute(
            select(Appointment).where(Appointment.id == due_id).with_for_update()
        )
        # The connection has lock_timeout=5s: waiting instead of skipping would raise.
        assert run() == 0
    assert run() == 1
