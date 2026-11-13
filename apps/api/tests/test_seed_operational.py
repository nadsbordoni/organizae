"""Operational seed integration tests against disposable SQLite only."""

from collections import Counter
from datetime import UTC, datetime, time, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, delete, event, insert, select
from sqlalchemy.orm import Session
from test_clients import business_a, business_b, database, password_hash

from app.core.config import settings
from app.db.base import Base
from app.modules.appointments.exceptions import AppointmentConflictError
from app.modules.appointments.models import Appointment, AppointmentStatus, BusinessHour
from app.modules.appointments.repository import AppointmentRepository
from app.modules.appointments.schemas import BlockCreateRequest
from app.modules.appointments.service import AppointmentService
from app.modules.categories.models import Category
from app.modules.clients.models import Client
from app.modules.clients.repository import ClientRepository
from app.modules.financial_categories.models import FinancialCategory
from app.modules.financial_entries.models import FinancialEntry
from app.modules.professionals.models import Professional
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.services.associations import professional_services
from app.modules.services.exceptions import ServiceConflictError
from app.modules.services.models import Service
from app.modules.services.service import ServiceService
from scripts import seed_operational as seed

__all__ = ["database", "password_hash"]
TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
FINANCIAL_TABLES = ("financial_entries", "financial_categories", "recurring_entries")


@pytest.fixture(autouse=True)
def sqlite_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    original_busy = AppointmentRepository.list_busy
    original_create = AppointmentRepository.create
    original_overlap = AppointmentRepository.has_overlap
    original_count = AppointmentRepository.count_future_by_phone

    def busy(self, **kwargs):
        kwargs["starts_at"] = kwargs["starts_at"].astimezone(UTC)
        kwargs["ends_at"] = kwargs["ends_at"].astimezone(UTC)
        return [
            (start.replace(tzinfo=UTC), end.replace(tzinfo=UTC))
            for start, end in original_busy(self, **kwargs)
        ]

    def create(self, appointment):
        # Match PostgreSQL storage; SQLite discards timezone offsets.
        appointment.starts_at = appointment.starts_at.astimezone(UTC)
        appointment.ends_at = appointment.ends_at.astimezone(UTC)
        return original_create(self, appointment)

    def overlap(self, **kwargs):
        kwargs["starts_at"] = kwargs["starts_at"].astimezone(UTC)
        kwargs["ends_at"] = kwargs["ends_at"].astimezone(UTC)
        return original_overlap(self, **kwargs)

    def count(self, **kwargs):
        kwargs["now"] = kwargs["now"].astimezone(UTC)
        return original_count(self, **kwargs)

    monkeypatch.setattr(AppointmentRepository, "has_overlap", overlap)
    monkeypatch.setattr(AppointmentRepository, "count_future_by_phone", count)
    monkeypatch.setattr(AppointmentRepository, "list_busy", busy)
    monkeypatch.setattr(AppointmentRepository, "create", create)


def run_seed(
    database: Engine, business_id: UUID = business_a, now: datetime = NOW
) -> dict:
    return seed.seed_operational(database, business_id, app_env="test", tz=TZ, now=now)


def snapshot(database: Engine) -> dict:
    with database.connect() as connection:
        return {
            table.name: sorted(
                (
                    tuple(str(value) for value in row)
                    for row in connection.execute(select(table))
                ),
                key=str,
            )
            for table in Base.metadata.sorted_tables
        }


def seeded(session: Session, model: type, business_id: UUID = business_a) -> list:
    marker = model.notes if model in (Client, Appointment) else model.name
    return list(
        session.scalars(
            select(model).where(
                model.business_id == business_id,
                marker.startswith(seed.MARKER, autoescape=True),
            )
        )
    )


def test_counts_relationships_statuses_and_dates(database: Engine) -> None:
    before = snapshot(database)
    result = run_seed(database)
    assert result["unavailable"] == []
    assert result["created"] == {
        "categories": 4,
        "professionals": 6,
        "services": 12,
        "professional_services": 36,
        "clients": 80,
        "business_hours": 12,
        "bookings": 200,
        "blocks": 6,
    }
    assert result["reference_date"] == NOW.astimezone(TZ).date().isoformat()
    after = snapshot(database)
    for table in ("businesses", "users", *FINANCIAL_TABLES):
        assert after[table] == before[table]
    with Session(database) as session:
        professionals = seeded(session, Professional)
        services = seeded(session, Service)
        categories = seeded(session, Category)
        assert len(categories) == 4
        category_ids = {item.id for item in categories}
        assert all(item.category_id in category_ids for item in services)
        clients = seeded(session, Client)
        appointments = seeded(session, Appointment)
        assert (len(professionals), len(services), len(clients), len(appointments)) == (
            6,
            12,
            80,
            206,
        )
        assert all(
            record.id.version == 4
            for record in [*professionals, *services, *clients, *appointments]
        )
        assert all(record.is_active for record in [*professionals, *services])
        assert len({service.price for service in services}) > 6
        assert {service.duration_minutes for service in services} == {
            15,
            30,
            45,
            60,
            90,
            120,
        }
        assert Counter(item.status for item in appointments) == {
            AppointmentStatus.CONFIRMED: 120,
            AppointmentStatus.CANCELLED: 40,
            AppointmentStatus.PENDING: 40,
            AppointmentStatus.BLOCKED: 6,
        }
        by_service = {item.id: item for item in services}
        by_phone = {item.phone: item for item in clients}
        links = set(
            session.execute(
                select(
                    professional_services.c.professional_id,
                    professional_services.c.service_id,
                ).where(professional_services.c.business_id == business_a)
            ).all()
        )
        assert len(links) == 36
        hours = list(
            session.scalars(
                select(BusinessHour).where(BusinessHour.business_id == business_a)
            )
        )
        past, future = 0, 0
        for item in appointments:
            start, end = (
                item.starts_at.replace(tzinfo=UTC),
                item.ends_at.replace(tzinfo=UTC),
            )
            local_start, local_end = start.astimezone(TZ), end.astimezone(TZ)
            assert item.created_at.replace(tzinfo=UTC) < start
            assert any(
                hour.weekday == local_start.weekday()
                and hour.opens_at
                <= local_start.time()
                < local_end.time()
                <= hour.closes_at
                and (
                    datetime.combine(local_start.date(), hour.opens_at, TZ)
                    - local_start
                ).total_seconds()
                % 1800
                == 0
                for hour in hours
            )
            if item.status == AppointmentStatus.BLOCKED:
                assert item.service_id is None and item.customer_phone is None
            else:
                assert (item.professional_id, item.service_id) in links
                assert item.customer_name == by_phone[item.customer_phone].name
                assert end - start == timedelta(
                    minutes=by_service[item.service_id].duration_minutes
                )
                past += start < NOW
                future += start > NOW
        assert (past, future) == (100, 100)
        for client in clients:
            related = ClientRepository(session).list_appointments(client)
            assert len(related) in (2, 3)
            assert all(item.business_id == business_a for item in related)
        busy = [
            item for item in appointments if item.status != AppointmentStatus.CANCELLED
        ]
        for index, first in enumerate(busy):
            for second in busy[index + 1 :]:
                if (
                    first.professional_id is None
                    or second.professional_id is None
                    or first.professional_id == second.professional_id
                ):
                    assert not (
                        first.starts_at < second.ends_at
                        and first.ends_at > second.starts_at
                    )


def test_idempotent_even_on_later_days_and_preserves_edits(database: Engine) -> None:
    run_seed(database)
    with Session(database) as session:
        record = next(
            item
            for item in seeded(session, Appointment)
            if item.status != AppointmentStatus.BLOCKED
        )
        record.notes += " edited"
        record.status = AppointmentStatus.CANCELLED
        service = seeded(session, Service)[0]
        service.price = 123
        session.commit()
    before = snapshot(database)
    result = run_seed(database, now=NOW + timedelta(days=14))
    assert all(value == 0 for value in result["created"].values())
    assert result["unavailable"] == []
    assert result["reference_date"] == NOW.astimezone(TZ).date().isoformat()
    assert snapshot(database) == before


def test_repairs_only_missing_rows_and_links(database: Engine) -> None:
    run_seed(database)
    with Session(database) as session:
        session.delete(session.get(Client, seed.fixture_id(business_a, "client:0")))
        session.delete(
            session.get(Appointment, seed.fixture_id(business_a, "booking:0"))
        )
        session.execute(
            delete(professional_services).where(
                professional_services.c.professional_id
                == seed.fixture_id(business_a, "professional:0"),
                professional_services.c.service_id
                == seed.fixture_id(business_a, "service:0"),
            )
        )
        session.commit()
    result = run_seed(database, now=NOW + timedelta(days=7))
    assert result["created"] == {
        "categories": 0,
        "professionals": 0,
        "services": 0,
        "professional_services": 1,
        "clients": 1,
        "business_hours": 0,
        "bookings": 1,
        "blocks": 0,
    }
    assert result["unavailable"] == []
    assert all(value == 0 for value in run_seed(database)["created"].values())


def test_respects_existing_hours_and_business_wide_blocks(database: Engine) -> None:
    with Session(database) as session:
        session.add(
            BusinessHour(
                business_id=business_a, weekday=0, opens_at=time(10), closes_at=time(12)
            )
        )
        session.commit()
        block = AppointmentService(session, TZ).create_block(
            BlockCreateRequest(
                starts_at=NOW + timedelta(days=1),
                ends_at=NOW + timedelta(days=25),
                notes="Existing closure",
            ),
            business_id=business_a,
        )
        identifier = block.id
    result = run_seed(database)
    assert result["created"]["business_hours"] == 0
    with Session(database) as session:
        hours = list(session.scalars(select(BusinessHour)))
        assert len(hours) == 1 and hours[0].opens_at == time(10)
        block = session.get(Appointment, identifier)
        for appointment in seeded(session, Appointment):
            assert not (
                appointment.starts_at < block.ends_at
                and appointment.ends_at > block.starts_at
            )
            local = appointment.starts_at.replace(tzinfo=UTC).astimezone(TZ)
            assert local.weekday() == 0 and local.time() >= time(10)


def test_closed_agenda_is_reported_without_forcing_bookings(database: Engine) -> None:
    with Session(database) as session:
        AppointmentService(session, TZ).create_block(
            BlockCreateRequest(
                starts_at=NOW - timedelta(days=120),
                ends_at=NOW + timedelta(days=120),
                notes="Existing complete closure",
            ),
            business_id=business_a,
        )
    before = snapshot(database)["appointments"]
    result = run_seed(database)
    assert result["created"]["bookings"] == result["created"]["blocks"] == 0
    assert len(result["unavailable"]) == 206
    assert snapshot(database)["appointments"] == before


def test_existing_links_catalog_and_phone_collisions_are_preserved(
    database: Engine,
) -> None:
    with Session(database) as session:
        record = Service(
            id=seed.fixture_id(business_a, "service:0"),
            business_id=business_a,
            name="Existing seed service edited",
            price=99,
            duration_minutes=45,
        )
        professional = Professional(
            id=seed.fixture_id(business_a, "professional:0"),
            business_id=business_a,
            name="Existing seed professional edited",
            is_active=True,
        )
        normal_service = session.scalar(
            select(Service).where(Service.business_id == business_a)
        )
        session.add_all([record, professional])
        session.flush()
        session.execute(
            insert(professional_services).values(
                professional_id=professional.id,
                service_id=normal_service.id,
                business_id=business_a,
            )
        )
        collision = Client(
            business_id=business_a, name="Existing fake phone", phone="00000000000"
        )
        session.add(collision)
        session.commit()
        collision_id = collision.id
        normal_service_id = normal_service.id
    result = run_seed(database)
    assert result["created"]["professionals"] == 5
    assert result["created"]["services"] == 11
    assert result["unavailable"] == []
    with Session(database) as session:
        assert (
            session.get(
                Service, seed.fixture_id(business_a, "service:0")
            ).duration_minutes
            == 45
        )
        assert (
            session.get(
                Professional, seed.fixture_id(business_a, "professional:0")
            ).name
            == "Existing seed professional edited"
        )
        assert session.get(Client, collision_id).phone == "00000000000"
        assert (
            session.get(Client, seed.fixture_id(business_a, "client:0")).phone
            != "00000000000"
        )
        assert (
            session.execute(
                select(professional_services).where(
                    professional_services.c.service_id == normal_service_id,
                    professional_services.c.professional_id
                    == seed.fixture_id(business_a, "professional:0"),
                )
            ).first()
            is not None
        )
    assert all(value == 0 for value in run_seed(database)["created"].values())


def test_two_businesses_have_independent_records(database: Engine) -> None:
    run_seed(database, business_a)
    before = snapshot(database)
    result = run_seed(database, business_b)
    assert result["created"]["bookings"] == 200
    with Session(database) as session:
        for business_id in (business_a, business_b):
            clients = seeded(session, Client, business_id)
            services = seeded(session, Service, business_id)
            professionals = seeded(session, Professional, business_id)
            appointments = seeded(session, Appointment, business_id)
            assert (
                len(clients),
                len(services),
                len(professionals),
                len(appointments),
            ) == (80, 12, 6, 206)
            assert all(item.business_id == business_id for item in appointments)
            categories = seeded(session, Category, business_id)
            assert len(categories) == 4
            category_ids = {item.id for item in categories}
            assert all(item.category_id in category_ids for item in services)
            service_ids = {item.id for item in services}
            professional_ids = {item.id for item in professionals}
            assert all(
                item.service_id is None or item.service_id in service_ids
                for item in appointments
            )
            assert all(
                item.professional_id is None or item.professional_id in professional_ids
                for item in appointments
            )
    after = snapshot(database)
    for table in ("users", "businesses", *FINANCIAL_TABLES):
        assert before[table] == after[table]
    for table in (
        "clients",
        "professionals",
        "services",
        "appointments",
        "business_hours",
        "professional_services",
    ):
        assert set(before[table]).issubset(set(after[table]))


def test_financial_records_are_untouched_and_no_financial_sql_is_executed(
    database: Engine,
) -> None:
    with Session(database) as session:
        category = FinancialCategory(
            business_id=business_a, name="Existing income", type="INCOME"
        )
        session.add(category)
        session.flush()
        recurrence = RecurringEntry(
            business_id=business_a,
            category_id=category.id,
            type="INCOME",
            description="Existing recurrence",
            amount=10,
            due_day=5,
            start_date=NOW.date(),
        )
        session.add(recurrence)
        entry = FinancialEntry(
            business_id=business_a,
            category_id=category.id,
            type="INCOME",
            description="Existing financial entry",
            amount=10,
            due_date=NOW.date(),
            status="PENDING",
        )
        session.add(entry)
        session.commit()
    before = snapshot(database)

    def forbid_financial_sql(
        connection, cursor, statement, parameters, context, executemany
    ):
        assert not any(table in statement.lower() for table in FINANCIAL_TABLES), (
            statement
        )

    event.listen(database, "before_cursor_execute", forbid_financial_sql)
    try:
        run_seed(database)
        run_seed(database)
    finally:
        event.remove(database, "before_cursor_execute", forbid_financial_sql)
    after = snapshot(database)
    for table in FINANCIAL_TABLES:
        assert before[table] == after[table]
    assert not any(
        "financial" in column.name for column in Appointment.__table__.columns
    )


def test_service_failure_rolls_back_even_after_internal_commits(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = snapshot(database)
    original = AppointmentService.book_panel
    calls = 0

    def fail(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise AppointmentConflictError("injected failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AppointmentService, "book_panel", fail)
    with pytest.raises(AppointmentConflictError, match="injected"):
        run_seed(database)
    assert calls == 4
    assert snapshot(database) == before


def test_missing_business_rolls_back_without_creating_anything(
    database: Engine,
) -> None:
    before = snapshot(database)
    with pytest.raises(seed.SeedError, match="encontrada"):
        run_seed(database, uuid4())
    assert snapshot(database) == before


@pytest.mark.parametrize("environment", ["production", "", "staging"])
def test_environment_guard_precedes_database_access(
    database: Engine, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    begin = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(database, "begin", begin)
    with pytest.raises(seed.SeedError, match="bloqueado"):
        seed.seed_operational(database, business_a, app_env=environment, tz=TZ, now=NOW)
    begin.assert_not_called()


def test_timezone_change_does_not_move_existing_seed(database: Engine) -> None:
    run_seed(database)
    before = snapshot(database)
    with pytest.raises(seed.SeedError, match="fuso"):
        seed.seed_operational(
            database, business_a, app_env="test", tz=ZoneInfo("UTC"), now=NOW
        )
    assert snapshot(database) == before


def test_inactive_existing_professional_is_not_reactivated(database: Engine) -> None:
    with Session(database) as session:
        session.add(
            Professional(
                id=seed.fixture_id(business_a, "professional:0"),
                business_id=business_a,
                name="Inactive seed professional",
                is_active=False,
            )
        )
        session.commit()
    result = run_seed(database)
    assert result["unavailable"]
    with Session(database) as session:
        assert not session.get(
            Professional, seed.fixture_id(business_a, "professional:0")
        ).is_active


def test_cli_guard_and_invalid_business_id_never_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.db.session as db

    fake_engine = Mock()
    fake_engine.begin.side_effect = AssertionError("must not connect")
    monkeypatch.setattr(db, "engine", fake_engine)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(SystemExit) as exc:
        seed.main(["--business-id", str(business_a)])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        seed.main(["--business-id", "invalid"])
    with pytest.raises(SystemExit):
        seed.main([])
    fake_engine.begin.assert_not_called()


def test_new_bookings_avoid_existing_manual_appointments(database: Engine) -> None:
    run_seed(database)
    with Session(database) as session:
        removed = session.get(Appointment, seed.fixture_id(business_a, "booking:100"))
        professional_id, service_id = removed.professional_id, removed.service_id
        start = removed.starts_at.replace(tzinfo=UTC)
        session.delete(removed)
        session.commit()
        from app.modules.appointments.schemas import OnlineBookingRequest

        manual = AppointmentService(session, TZ).book_panel(
            OnlineBookingRequest(
                professional_id=professional_id,
                service_id=service_id,
                starts_at=start,
                customer_name="Existing manual customer",
                customer_phone="00009999999",
            ),
            business_id=business_a,
            now=NOW,
        )
        manual_id = manual.id
    before = snapshot(database)["appointments"]
    result = run_seed(database)
    assert result["created"]["bookings"] == 1
    assert result["unavailable"] == []
    assert set(before).issubset(set(snapshot(database)["appointments"]))
    with Session(database) as session:
        manual = session.get(Appointment, manual_id)
        restored = session.get(Appointment, seed.fixture_id(business_a, "booking:100"))
        assert restored.starts_at != manual.starts_at
        assert not (
            restored.starts_at < manual.ends_at and restored.ends_at > manual.starts_at
        )


def test_persistent_sqlite_is_rejected_without_connecting() -> None:
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///operational_test")
    try:
        with pytest.raises(seed.SeedError, match="PostgreSQL"):
            seed.seed_operational(engine, business_a, app_env="test", tz=TZ, now=NOW)
    finally:
        engine.dispose()


def test_naive_clock_is_rejected_before_database_access(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    begin = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(database, "begin", begin)
    with pytest.raises(seed.SeedError, match="fuso"):
        run_seed(database, now=NOW.replace(tzinfo=None))
    begin.assert_not_called()


def test_legacy_seed_gets_categories_without_recreating_operational_data(
    database: Engine,
) -> None:
    run_seed(database)
    with Session(database) as session:
        for service in seeded(session, Service):
            service.category_id = None
        session.flush()
        for category in seeded(session, Category):
            session.delete(category)
        manual = Category(business_id=business_a, name="Manual category")
        session.add(manual)
        session.flush()
        selected = session.get(Service, seed.fixture_id(business_a, "service:0"))
        selected.category_id = manual.id
        selected.price = 123
        manual_id = manual.id
        session.commit()
    before = snapshot(database)
    result = run_seed(database, now=NOW + timedelta(days=1))
    assert result["created"]["categories"] == 4
    assert all(
        count == 0 for key, count in result["created"].items() if key != "categories"
    )
    assert result["linked_existing_services"] == 11
    after = snapshot(database)
    for table in (
        "appointments",
        "clients",
        "professionals",
        "professional_services",
        "business_hours",
        *FINANCIAL_TABLES,
    ):
        assert before[table] == after[table]
    with Session(database) as session:
        assert all(
            service.category_id is not None for service in seeded(session, Service)
        )
        selected = session.get(Service, seed.fixture_id(business_a, "service:0"))
        assert selected.category_id == manual_id and selected.price == 123
        ordinary = session.scalar(
            select(Service).where(
                Service.business_id == business_a, Service.name == "Haircut"
            )
        )
        assert ordinary.category_id is None
    repeated = run_seed(database, now=NOW + timedelta(days=2))
    assert all(count == 0 for count in repeated["created"].values())
    assert repeated["linked_existing_services"] == 0
    assert snapshot(database) == after


def test_category_name_reuse_is_case_insensitive_and_scoped_to_business(
    database: Engine,
) -> None:
    with Session(database) as session:
        own = Category(business_id=business_a, name=f"{seed.MARKER} CORTES")
        foreign = Category(business_id=business_b, name=f"{seed.MARKER} Cortes")
        session.add_all([own, foreign])
        session.commit()
        own_id, foreign_id = own.id, foreign.id
    result = run_seed(database)
    assert result["created"]["categories"] == 3
    with Session(database) as session:
        categories = seeded(session, Category)
        assert len(categories) == 4
        assert (
            session.get(Service, seed.fixture_id(business_a, "service:0")).category_id
            == own_id
        )
        assert session.get(Category, foreign_id).name == f"{seed.MARKER} Cortes"
        assert all(
            service.category_id != foreign_id for service in seeded(session, Service)
        )
        names = {
            category.id: category.name.removeprefix(f"{seed.MARKER} ").lower()
            for category in categories
        }
        assert Counter(
            names[service.category_id] for service in seeded(session, Service)
        ) == {"cortes": 5, "barba": 2, "tratamentos": 3, "combos": 2}
    assert all(count == 0 for count in run_seed(database)["created"].values())


def test_category_backfill_rolls_back_after_service_commit(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_seed(database)
    with Session(database) as session:
        for index in (0, 1):
            session.get(
                Service, seed.fixture_id(business_a, f"service:{index}")
            ).category_id = None
        session.commit()
    before = snapshot(database)
    original = ServiceService.update
    calls = 0

    def fail(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ServiceConflictError("injected category failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ServiceService, "update", fail)
    with pytest.raises(ServiceConflictError, match="injected"):
        run_seed(database)
    assert calls == 2
    assert snapshot(database) == before
