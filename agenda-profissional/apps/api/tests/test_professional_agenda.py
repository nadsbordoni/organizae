from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_service_repository import businesses, session

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

from app.db.session import get_db
from app.modules.appointments.exceptions import InvalidBookingError
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
)
from app.modules.appointments.repository import AppointmentRepository
from app.modules.appointments.schemas import ProfessionalAgendaItem
from app.modules.appointments.service import AppointmentService
from app.modules.auth.dependencies import get_current_user
from app.modules.businesses.models import Business
from app.modules.professionals.dependencies import get_current_professional
from app.modules.professionals.models import Professional
from app.modules.professionals.repository import ProfessionalRepository
from app.modules.services.models import Service
from app.modules.users.models import User

__all__ = ["businesses", "session"]

S = AppointmentStatus
agenda_path = "/api/v1/professionals/me/appointments"
day = datetime(2026, 11, 30, tzinfo=UTC)
period = {"starts_at": day.isoformat(), "ends_at": (day + timedelta(days=1)).isoformat()}
# What the professional may see; any new field must be a conscious decision.
AGENDA_FIELDS = {
    "id",
    "starts_at",
    "ends_at",
    "status",
    "service_name",
    "customer_name",
    "customer_phone",
}


def at(hour: int, days: int = 0) -> datetime:
    return day + timedelta(days=days, hours=hour)


def agenda_item(**overrides: object) -> ProfessionalAgendaItem:
    data = {
        "id": uuid4(),
        "starts_at": at(9),
        "ends_at": at(10),
        "status": S.CONFIRMED,
        "service_name": "Haircut",
        "customer_name": "Maria Silva",
        "customer_phone": "81987570102",
    }
    return ProfessionalAgendaItem(**{**data, **overrides})


def test_agenda_item_exposes_only_what_the_professional_needs() -> None:
    assert set(ProfessionalAgendaItem.model_fields) == AGENDA_FIELDS


# --- service rules (mocked repository) ---


@pytest.fixture
def appointment_service() -> AppointmentService:
    service = AppointmentService(Mock(spec=Session), ZoneInfo("America/Sao_Paulo"))
    service.repository = Mock(spec=AppointmentRepository)
    service.repository.list_for_professional.return_value = []
    return service


@pytest.fixture
def professional() -> Professional:
    return Professional(id=uuid4(), business_id=uuid4(), name="Ana", is_active=True)


def test_agenda_is_scoped_by_the_professional_and_their_business(
    appointment_service: AppointmentService, professional: Professional
) -> None:
    appointment = Appointment(
        id=uuid4(),
        business_id=professional.business_id,
        professional_id=professional.id,
        service_id=uuid4(),
        customer_name="Maria Silva",
        customer_phone="81987570102",
        customer_email="maria@example.com",
        notes="internal note",
        starts_at=at(9),
        ends_at=at(10),
        status=S.CONFIRMED,
        source=AppointmentSource.ONLINE,
    )
    appointment_service.repository.list_for_professional.return_value = [
        (appointment, "Haircut")
    ]

    items = appointment_service.list_professional_agenda(
        professional=professional, starts_at=at(0), ends_at=at(24)
    )

    appointment_service.repository.list_for_professional.assert_called_once_with(
        business_id=professional.business_id,
        professional_id=professional.id,
        starts_at=at(0),
        ends_at=at(24),
        status=None,
    )
    assert [item.model_dump() for item in items] == [
        {
            "id": appointment.id,
            "starts_at": at(9),
            "ends_at": at(10),
            "status": S.CONFIRMED,
            "service_name": "Haircut",
            "customer_name": "Maria Silva",
            "customer_phone": "81987570102",
        }
    ]


def test_agenda_passes_the_status_filter(
    appointment_service: AppointmentService, professional: Professional
) -> None:
    appointment_service.list_professional_agenda(
        professional=professional, starts_at=at(0), ends_at=at(24), status=S.PENDING
    )
    kwargs = appointment_service.repository.list_for_professional.call_args.kwargs
    assert kwargs["status"] is S.PENDING


@pytest.mark.parametrize(
    ("starts_at", "ends_at"),
    [
        (at(10), at(10)),
        (at(10), at(9)),
        (at(0), at(0, days=32)),
    ],
)
def test_agenda_rejects_invalid_ranges(
    appointment_service: AppointmentService,
    professional: Professional,
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    with pytest.raises(InvalidBookingError):
        appointment_service.list_professional_agenda(
            professional=professional, starts_at=starts_at, ends_at=ends_at
        )
    appointment_service.repository.list_for_professional.assert_not_called()


# --- who is a professional (dependency) ---


def call_dependency(found: Professional | None) -> Professional:
    user = User(id=uuid4(), name="Ana", email="ana@example.com", is_active=True)
    with patch(
        "app.modules.professionals.dependencies.ProfessionalRepository"
    ) as repository:
        repository.return_value.get_by_user_id.return_value = found
        result = get_current_professional(user, Mock(spec=Session))
    repository.return_value.get_by_user_id.assert_called_once_with(user.id)
    return result


def test_dependency_returns_the_professional_linked_to_the_user(
    professional: Professional,
) -> None:
    assert call_dependency(professional) is professional


def test_dependency_refuses_a_user_without_professional_profile() -> None:
    with pytest.raises(HTTPException) as error:
        call_dependency(None)
    assert error.value.status_code == 403


def test_dependency_refuses_an_inactive_professional(
    professional: Professional,
) -> None:
    professional.is_active = False
    with pytest.raises(HTTPException) as error:
        call_dependency(professional)
    assert error.value.status_code == 403


# --- queries (SQLite created from the metadata) ---


def test_user_is_linked_to_at_most_one_professional(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    user = User(name="Ana", email="ana@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    linked = Professional(business_id=businesses[0].id, name="Ana", user_id=user.id)
    session.add(linked)
    session.flush()

    repository = ProfessionalRepository(session)
    assert repository.get_by_user_id(user.id) is linked
    assert repository.get_by_user_id(uuid4()) is None

    session.add(Professional(business_id=businesses[0].id, name="Ana 2", user_id=user.id))
    with pytest.raises(IntegrityError):
        session.flush()


class Agenda:
    """Appointments of three professionals in two businesses, ids by role."""

    def __init__(self, session: Session, businesses: tuple[Business, Business]) -> None:
        first, second = businesses
        self.business_id = first.id
        self.other_business_id = second.id
        service = Service(
            business_id=first.id,
            name="Haircut",
            price=Decimal("25.50"),
            duration_minutes=60,
        )
        foreign_service = Service(
            business_id=second.id,
            name="Foreign service",
            price=Decimal(10),
            duration_minutes=60,
        )
        mine = Professional(business_id=first.id, name="Ana")
        colleague = Professional(business_id=first.id, name="Bia")
        foreign = Professional(business_id=second.id, name="Caio")
        session.add_all([service, foreign_service, mine, colleague, foreign])
        session.flush()
        self.professional_id = mine.id

        def add(
            professional: Professional | None, status: S, hour: int, days: int = 0
        ) -> UUID:
            booked = status is not S.BLOCKED
            business = second if professional is foreign else first
            appointment = Appointment(
                business_id=business.id,
                professional_id=professional.id if professional else None,
                service_id=(
                    (foreign_service if professional is foreign else service).id
                    if booked
                    else None
                ),
                customer_name="Maria Silva" if booked else None,
                customer_phone="81987570102" if booked else None,
                customer_email="maria@example.com" if booked else None,
                notes="internal note",
                starts_at=at(hour, days),
                ends_at=at(hour + 1, days),
                status=status,
                source=AppointmentSource.PANEL,
            )
            session.add(appointment)
            session.flush()
            return appointment.id

        self.confirmed = add(mine, S.CONFIRMED, 9)
        self.pending = add(mine, S.PENDING, 10)
        self.cancelled = add(mine, S.CANCELLED, 11)
        self.own_block = add(mine, S.BLOCKED, 12)
        self.business_block = add(None, S.BLOCKED, 13)
        self.colleague = add(colleague, S.CONFIRMED, 9)
        self.foreign = add(foreign, S.CONFIRMED, 9)
        self.next_day = add(mine, S.CONFIRMED, 9, days=1)


@pytest.fixture
def agenda(session: Session, businesses: tuple[Business, Business]) -> Agenda:
    return Agenda(session, businesses)


def list_agenda(
    session: Session, agenda: Agenda, **overrides: object
) -> list[tuple[Appointment, str]]:
    arguments = {
        "business_id": agenda.business_id,
        "professional_id": agenda.professional_id,
        "starts_at": at(0),
        "ends_at": at(24),
        **overrides,
    }
    return AppointmentRepository(session).list_for_professional(**arguments)


def test_repository_lists_only_my_bookings_of_the_period_in_order(
    session: Session, agenda: Agenda
) -> None:
    rows = list_agenda(session, agenda)

    assert [appointment.id for appointment, _ in rows] == [
        agenda.confirmed,
        agenda.pending,
        agenda.cancelled,
    ]
    assert {service_name for _, service_name in rows} == {"Haircut"}


def test_repository_filters_by_status(session: Session, agenda: Agenda) -> None:
    rows = list_agenda(session, agenda, status=S.PENDING)
    assert [appointment.id for appointment, _ in rows] == [agenda.pending]


def test_repository_never_crosses_businesses(session: Session, agenda: Agenda) -> None:
    assert list_agenda(session, agenda, business_id=agenda.other_business_id) == []


def test_repository_does_not_mix_in_another_professional(
    session: Session, agenda: Agenda
) -> None:
    colleague = session.get(Appointment, agenda.colleague)
    rows = list_agenda(session, agenda, professional_id=colleague.professional_id)
    assert [appointment.id for appointment, _ in rows] == [agenda.colleague]


# --- HTTP ---


@pytest.fixture
def api_client(
    professional: Professional,
) -> Iterator[tuple[TestClient, Mock, Professional]]:
    service = Mock(spec=AppointmentService)
    service.list_professional_agenda.return_value = []
    app.dependency_overrides[get_appointment_service] = lambda: service
    app.dependency_overrides[get_current_professional] = lambda: professional
    try:
        with TestClient(app) as client:
            yield client, service, professional
    finally:
        for dependency in (
            get_appointment_service,
            get_current_professional,
            get_current_user,
            get_db,
        ):
            app.dependency_overrides.pop(dependency, None)


def test_professional_sees_their_agenda_without_private_data(
    api_client: tuple[TestClient, Mock, Professional],
) -> None:
    client, service, professional = api_client
    item = agenda_item()
    service.list_professional_agenda.return_value = [item]

    response = client.get(agenda_path, params=period)

    assert response.status_code == 200
    [body] = response.json()
    assert set(body) == AGENDA_FIELDS
    assert body["id"] == str(item.id)
    assert body["service_name"] == "Haircut"
    assert body["customer_phone"] == "81987570102"
    kwargs = service.list_professional_agenda.call_args.kwargs
    assert kwargs["professional"] is professional
    assert kwargs["status"] is None


def test_professional_cannot_ask_for_someone_elses_agenda(
    api_client: tuple[TestClient, Mock, Professional],
) -> None:
    client, service, professional = api_client

    response = client.get(
        agenda_path,
        params={
            **period,
            "professional_id": str(uuid4()),
            "business_id": str(uuid4()),
        },
    )

    assert response.status_code == 200
    kwargs = service.list_professional_agenda.call_args.kwargs
    assert kwargs["professional"] is professional
    assert set(kwargs) == {"professional", "starts_at", "ends_at", "status"}


def test_agenda_status_filter(
    api_client: tuple[TestClient, Mock, Professional],
) -> None:
    client, service, _ = api_client
    response = client.get(agenda_path, params={**period, "status": "CONFIRMED"})
    assert response.status_code == 200
    assert service.list_professional_agenda.call_args.kwargs["status"] is S.CONFIRMED


def test_agenda_requires_a_period(
    api_client: tuple[TestClient, Mock, Professional],
) -> None:
    client, service, _ = api_client
    assert client.get(agenda_path).status_code == 422
    service.list_professional_agenda.assert_not_called()


def test_agenda_invalid_range_is_a_422(
    api_client: tuple[TestClient, Mock, Professional],
) -> None:
    client, service, _ = api_client
    service.list_professional_agenda.side_effect = InvalidBookingError(
        "Range must be positive and at most 31 days"
    )
    response = client.get(agenda_path, params=period)
    assert response.status_code == 422
    assert response.json() == {"detail": "Range must be positive and at most 31 days"}


def test_agenda_requires_authentication(
    api_client: tuple[TestClient, Mock, Professional],
) -> None:
    client, service, _ = api_client
    app.dependency_overrides.pop(get_current_professional)
    assert client.get(agenda_path, params=period).status_code == 401
    service.list_professional_agenda.assert_not_called()


def test_user_who_is_not_a_professional_gets_403(
    api_client: tuple[TestClient, Mock, Professional],
) -> None:
    client, service, _ = api_client
    app.dependency_overrides.pop(get_current_professional)
    owner = User(id=uuid4(), business_id=uuid4(), is_active=True)
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_db] = lambda: Mock(spec=Session)

    with patch(
        "app.modules.professionals.dependencies.ProfessionalRepository"
    ) as repository:
        repository.return_value.get_by_user_id.return_value = None
        response = client.get(agenda_path, params=period)

    assert response.status_code == 403
    assert response.json() == {"detail": "User is not an active professional"}
    service.list_professional_agenda.assert_not_called()


# --- migration ---


def test_migration_links_users_to_professionals() -> None:
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
    revision = script.get_revision("b8d3f1a6c204")
    assert revision.revision in {
        item.revision for item in script.iterate_revisions("head", "base")
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()
    assert "ALTER TABLE professionals ADD COLUMN user_id" in sql
    assert "fk_professionals_user_id_users" in sql
    assert "uq_professionals_user_id" in sql
