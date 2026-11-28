from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_appointments import at, booking_at, business_id, now, service
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
    from app.modules.notifications.route import get_notification_service

from app.modules.appointments.exceptions import AppointmentConflictError
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
)
from app.modules.appointments.service import AppointmentService
from app.modules.auth.dependencies import get_current_user
from app.modules.businesses.models import Business
from app.modules.notifications.models import Notification, NotificationKind
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import (
    NotificationAppointment,
    NotificationResponse,
)
from app.modules.notifications.service import NotificationService
from app.modules.professionals.models import Professional
from app.modules.services.models import Service
from app.modules.users.models import User

__all__ = ["businesses", "service", "session"]

S = AppointmentStatus
path = "/api/v1/notifications"
RESPONSE_FIELDS = {"id", "kind", "read", "created_at", "appointment"}
APPOINTMENT_FIELDS = {
    "id",
    "status",
    "starts_at",
    "ends_at",
    "customer_name",
    "service_name",
}


# --- the booking creates the notification (service, mocked repositories) ---


@pytest.fixture
def notifications(service: AppointmentService) -> Mock:
    def assign_id(appointment: Appointment) -> Appointment:
        appointment.id = uuid4()
        return appointment

    service.repository.create.side_effect = assign_id
    service.notification_repository = Mock(spec=NotificationRepository)
    return service.notification_repository


def test_online_booking_notifies_the_owner_in_the_same_transaction(
    service: AppointmentService, notifications: Mock
) -> None:
    order = Mock()
    order.attach_mock(notifications.create, "notify")
    order.attach_mock(service.session.commit, "commit")

    appointment = service.book_online(
        booking_at(at(9)), business_id=business_id, now=now
    )

    [notification] = notifications.create.call_args.args
    assert notification.business_id == business_id
    assert notification.appointment_id == appointment.id
    assert notification.kind is NotificationKind.BOOKING_CREATED
    assert notification.read_at is None
    assert [call[0] for call in order.mock_calls] == ["notify", "commit"]
    assert appointment.source is AppointmentSource.ONLINE
    assert appointment.status is S.PENDING


def test_booking_made_in_the_panel_does_not_notify(
    service: AppointmentService, notifications: Mock
) -> None:
    service.book_panel(booking_at(at(9)), business_id=business_id, now=now)
    notifications.create.assert_not_called()


def test_refused_online_booking_does_not_notify(
    service: AppointmentService, notifications: Mock
) -> None:
    with pytest.raises(AppointmentConflictError):
        service.book_online(booking_at(at(8)), business_id=business_id, now=now)
    notifications.create.assert_not_called()


def test_booking_is_undone_when_the_notification_cannot_be_saved(
    service: AppointmentService, notifications: Mock
) -> None:
    notifications.create.side_effect = IntegrityError("insert", {}, Exception())
    with pytest.raises(AppointmentConflictError):
        service.book_online(booking_at(at(9)), business_id=business_id, now=now)
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


# --- reading the notifications ---


def make_response(**overrides: object) -> NotificationResponse:
    data = {
        "id": uuid4(),
        "kind": NotificationKind.BOOKING_CREATED,
        "read": False,
        "created_at": at(9),
        "appointment": NotificationAppointment(
            id=uuid4(),
            status=S.PENDING,
            starts_at=at(10),
            ends_at=at(11),
            customer_name="Maria Silva",
            service_name="Haircut",
        ),
    }
    return NotificationResponse(**{**data, **overrides})


def test_service_builds_the_response_from_the_rows() -> None:
    unread = Notification(id=uuid4(), kind=NotificationKind.BOOKING_CREATED)
    unread.created_at = at(9)
    read = Notification(id=uuid4(), kind=NotificationKind.BOOKING_CREATED)
    read.created_at = at(8)
    read.read_at = at(8, 30)
    appointment = Appointment(
        id=uuid4(),
        customer_name="Maria Silva",
        customer_phone="81987570102",
        customer_email="maria@example.com",
        notes="internal note",
        starts_at=at(10),
        ends_at=at(11),
        status=S.PENDING,
    )
    notification_service = NotificationService(Mock(spec=Session))
    notification_service.repository = Mock(spec=NotificationRepository)
    notification_service.repository.list.return_value = [
        (unread, appointment, "Haircut"),
        (read, appointment, "Haircut"),
    ]

    items = notification_service.list(business_id=business_id, offset=5, limit=10)

    notification_service.repository.list.assert_called_once_with(
        business_id=business_id, offset=5, limit=10
    )
    assert [item.read for item in items] == [False, True]
    assert items[0].appointment.model_dump() == {
        "id": appointment.id,
        "status": S.PENDING,
        "starts_at": at(10),
        "ends_at": at(11),
        "customer_name": "Maria Silva",
        "service_name": "Haircut",
    }
    assert set(items[0].appointment.model_dump()) == APPOINTMENT_FIELDS


# --- queries (SQLite created from the metadata) ---


class Booked:
    """One appointment per business, so notifications can be mixed up on purpose."""

    def __init__(self, session: Session, businesses: tuple[Business, Business]) -> None:
        self.session = session
        self.first, self.second = (self._appointment(item) for item in businesses)

    def _appointment(self, business: Business) -> Appointment:
        service = Service(
            business_id=business.id,
            name=f"Service of {business.name}",
            price=Decimal("25.50"),
            duration_minutes=60,
        )
        professional = Professional(business_id=business.id, name="Ana")
        self.session.add_all([service, professional])
        self.session.flush()
        appointment = Appointment(
            business_id=business.id,
            professional_id=professional.id,
            service_id=service.id,
            customer_name="Maria Silva",
            customer_phone="81987570102",
            starts_at=at(9),
            ends_at=at(10),
            status=S.PENDING,
            source=AppointmentSource.ONLINE,
        )
        self.session.add(appointment)
        self.session.flush()
        return appointment


@pytest.fixture
def booked(session: Session, businesses: tuple[Business, Business]) -> Booked:
    return Booked(session, businesses)


def notify(
    session: Session, appointment: Appointment, created_at: datetime
) -> Notification:
    return NotificationRepository(session).create(
        Notification(
            business_id=appointment.business_id,
            appointment_id=appointment.id,
            kind=NotificationKind.BOOKING_CREATED,
            created_at=created_at,
        )
    )


def test_repository_lists_newest_first_with_appointment_and_service_name(
    session: Session, booked: Booked
) -> None:
    older = notify(session, booked.first, datetime(2026, 11, 30, 8, tzinfo=UTC))
    newer = notify(session, booked.first, datetime(2026, 11, 30, 9, tzinfo=UTC))

    rows = NotificationRepository(session).list(business_id=booked.first.business_id)

    assert [notification.id for notification, _, _ in rows] == [newer.id, older.id]
    assert {appointment.id for _, appointment, _ in rows} == {booked.first.id}
    assert {name for _, _, name in rows} == {"Service of First"}


def test_repository_only_lists_notifications_of_the_business(
    session: Session, booked: Booked
) -> None:
    mine = notify(session, booked.first, datetime(2026, 11, 30, 8, tzinfo=UTC))
    notify(session, booked.second, datetime(2026, 11, 30, 9, tzinfo=UTC))

    rows = NotificationRepository(session).list(business_id=booked.first.business_id)

    assert [notification.id for notification, _, _ in rows] == [mine.id]


def test_repository_paginates(session: Session, booked: Booked) -> None:
    start = datetime(2026, 11, 30, 8, tzinfo=UTC)
    created = [
        notify(session, booked.first, start + timedelta(hours=hour))
        for hour in range(3)
    ]
    repository = NotificationRepository(session)

    page = repository.list(business_id=booked.first.business_id, offset=1, limit=1)

    assert [notification.id for notification, _, _ in page] == [created[1].id]


def test_notification_cannot_point_to_an_appointment_of_another_business(
    session: Session, booked: Booked
) -> None:
    with pytest.raises(IntegrityError):
        NotificationRepository(session).create(
            Notification(
                business_id=booked.first.business_id,
                appointment_id=booked.second.id,
                kind=NotificationKind.BOOKING_CREATED,
            )
        )


# --- HTTP ---


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, Mock]]:
    notification_service = Mock(spec=NotificationService)
    notification_service.list.return_value = []
    app.dependency_overrides[get_notification_service] = lambda: notification_service
    try:
        with TestClient(app) as client:
            yield client, notification_service
    finally:
        app.dependency_overrides.pop(get_notification_service, None)
        app.dependency_overrides.pop(get_current_user, None)


def login(business: UUID | None = business_id) -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid4(), business_id=business, is_active=True
    )


def test_notifications_require_authentication(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, notification_service = api_client
    assert client.get(path).status_code == 401
    notification_service.list.assert_not_called()


def test_user_without_a_business_has_no_notifications(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, notification_service = api_client
    login(business=None)
    assert client.get(path).status_code == 403
    notification_service.list.assert_not_called()


def test_owner_lists_the_notifications_of_their_business(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, notification_service = api_client
    login()
    item = make_response()
    notification_service.list.return_value = [item]

    response = client.get(path)

    assert response.status_code == 200
    [body] = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert set(body["appointment"]) == APPOINTMENT_FIELDS
    assert body["id"] == str(item.id)
    assert body["kind"] == "BOOKING_CREATED"
    assert body["read"] is False
    assert body["appointment"]["service_name"] == "Haircut"
    notification_service.list.assert_called_once_with(
        business_id=business_id, offset=0, limit=100
    )


def test_business_comes_from_the_login_not_from_the_request(
    api_client: tuple[TestClient, Mock],
) -> None:
    client, notification_service = api_client
    login()

    client.get(path, params={"business_id": str(uuid4())})

    assert notification_service.list.call_args.kwargs["business_id"] == business_id


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}]
)
def test_pagination_is_validated(
    api_client: tuple[TestClient, Mock], params: dict[str, object]
) -> None:
    client, notification_service = api_client
    login()
    assert client.get(path, params=params).status_code == 422
    notification_service.list.assert_not_called()


# --- migration ---


def test_migration_creates_notifications_tied_to_the_same_business() -> None:
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
    revision = script.get_revision("c7e4a2b91d38")
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
    assert "CREATE TABLE notifications" in sql
    assert "notificationkind" in sql
    assert "fk_notifications_appointment_business" in sql
    assert "ON DELETE CASCADE" in sql
    assert "ix_notifications_business_created" in sql
