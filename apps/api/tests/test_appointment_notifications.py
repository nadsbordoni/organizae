import smtplib
import ssl
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
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
    from app.core.config import settings

from app.modules.appointments import notifications
from app.modules.appointments.exceptions import AppointmentConflictError
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
)
from app.modules.appointments.repository import AppointmentRepository
from app.modules.appointments.schemas import AppointmentStatusUpdate
from app.modules.appointments.service import AppointmentService
from app.modules.business_categories.models import BusinessCategory  # noqa: F401
from app.modules.businesses.models import Business
from app.modules.businesses.repository import BusinessRepository
from app.modules.users.models import User  # noqa: F401  (registers the mapper)

tz = ZoneInfo("America/Sao_Paulo")
business_id = uuid4()
monday_10h = datetime.combine(date(2026, 11, 9), time(10), tz)
CONFIRM = AppointmentStatusUpdate(status=AppointmentStatus.CONFIRMED)


def booking(**overrides: object) -> Appointment:
    values = {
        "id": uuid4(),
        "business_id": business_id,
        "professional_id": uuid4(),
        "service_id": uuid4(),
        "customer_name": "Maria Silva",
        "customer_phone": "81987570102",
        "customer_email": "maria@example.com",
        "starts_at": monday_10h,
        "ends_at": monday_10h,
        "status": AppointmentStatus.PENDING,
        "source": AppointmentSource.ONLINE,
    }
    return Appointment(**{**values, **overrides})


@pytest.fixture
def service() -> AppointmentService:
    appointment_service = AppointmentService(Mock(spec=Session), tz)
    appointment_service.repository = Mock(spec=AppointmentRepository)
    appointment_service.repository.lock_business.return_value = business_id
    appointment_service.repository.get_booking_names.return_value = ("Corte", "Ana")
    appointment_service.business_repository = Mock(spec=BusinessRepository)
    appointment_service.business_repository.get_by_id.return_value = Business(
        id=business_id, name="Studio Bela"
    )
    return appointment_service


@pytest.fixture
def sent():
    with patch("app.modules.appointments.service.send_email") as send_email:
        yield send_email


def confirm(service: AppointmentService, appointment: Appointment) -> Appointment:
    service.repository.get_by_id.return_value = appointment
    return service.update_status(appointment.id, CONFIRM, business_id=business_id)


def test_confirmation_has_service_professional_date_and_time(
    service: AppointmentService, sent: Mock
) -> None:
    confirm(service, booking())
    to, subject, body = sent.call_args.args
    assert to == "maria@example.com"
    assert "Studio Bela" in subject
    assert "Olá, Maria!" in body
    assert "Serviço: Corte" in body
    assert "Profissional: Ana" in body
    assert "Data: segunda-feira, 09/11/2026" in body
    assert "Horário: 10:00" in body


def test_confirmation_uses_the_business_timezone(
    service: AppointmentService, sent: Mock
) -> None:
    utc = monday_10h.astimezone(ZoneInfo("UTC"))
    confirm(service, booking(starts_at=utc))
    assert "Horário: 10:00" in sent.call_args.args[2]


def test_confirmation_is_sent_once_per_confirmation(
    service: AppointmentService, sent: Mock
) -> None:
    appointment = confirm(service, booking())
    assert appointment.status == AppointmentStatus.CONFIRMED
    confirm(service, appointment)
    sent.assert_called_once()


def test_confirmation_is_sent_after_the_commit(
    service: AppointmentService, sent: Mock
) -> None:
    order = Mock()
    order.attach_mock(service.session.commit, "commit")
    order.attach_mock(sent, "send")
    confirm(service, booking())
    assert [call[0] for call in order.mock_calls] == ["commit", "send"]


@pytest.mark.parametrize(
    "overrides",
    [{"customer_email": None}, {"service_id": None}],
    ids=["no-email", "block-without-service"],
)
def test_no_confirmation_when_there_is_nothing_to_send(
    service: AppointmentService, sent: Mock, overrides: dict
) -> None:
    confirm(service, booking(**overrides))
    sent.assert_not_called()


def test_cancelled_booking_is_not_confirmed_nor_notified(
    service: AppointmentService, sent: Mock
) -> None:
    with pytest.raises(AppointmentConflictError):
        confirm(service, booking(status=AppointmentStatus.CANCELLED))
    sent.assert_not_called()


def test_cancelling_does_not_send_a_confirmation(
    service: AppointmentService, sent: Mock
) -> None:
    service.repository.get_by_id.return_value = booking()
    service.update_status(
        uuid4(),
        AppointmentStatusUpdate(status=AppointmentStatus.CANCELLED),
        business_id=business_id,
    )
    sent.assert_not_called()


def test_email_failure_does_not_undo_the_confirmation(
    service: AppointmentService, sent: Mock
) -> None:
    sent.return_value = False
    appointment = confirm(service, booking())
    assert appointment.status == AppointmentStatus.CONFIRMED
    service.session.commit.assert_called_once_with()
    service.session.rollback.assert_not_called()


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "SMTP_USER", "studio@test")
    monkeypatch.setattr(settings, "EMAIL_FROM", "Studio Bela <studio@test>")
    with patch.object(notifications.smtplib, "SMTP") as smtp_class:
        yield smtp_class.return_value.__enter__.return_value


def test_send_email_delivers_over_verified_starttls(smtp: MagicMock) -> None:
    assert notifications.send_email("maria@example.com", "Assunto", "Corpo") is True
    smtp.starttls.assert_called_once()
    context = smtp.starttls.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    smtp.login.assert_called_once()
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "maria@example.com"
    assert message["From"] == "Studio Bela <studio@test>"
    assert message["Subject"] == "Assunto"


@pytest.mark.parametrize("error", [smtplib.SMTPException("boom"), OSError("down")])
def test_send_email_never_raises(smtp: MagicMock, error: Exception) -> None:
    smtp.send_message.side_effect = error
    assert notifications.send_email("maria@example.com", "Assunto", "Corpo") is False


def test_send_email_refuses_a_server_without_starttls(smtp: MagicMock) -> None:
    smtp.starttls.side_effect = smtplib.SMTPNotSupportedError("no STARTTLS")
    assert notifications.send_email("maria@example.com", "Assunto", "Corpo") is False
    smtp.login.assert_not_called()
    smtp.send_message.assert_not_called()


def test_send_email_without_smtp_configured_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    with patch.object(notifications.smtplib, "SMTP") as smtp_class:
        assert notifications.send_email("maria@example.com", "A", "B") is False
    smtp_class.assert_not_called()


now = monday_10h - timedelta(hours=20)
LEAD = timedelta(hours=24)


def remind(service: AppointmentService, *due: Appointment, **kwargs: object) -> int:
    service.repository.list_due_reminders.return_value = list(due)
    return service.send_due_reminders(lead_time=LEAD, now=now, **kwargs)


def test_reminder_has_service_professional_date_and_time(
    service: AppointmentService, sent: Mock
) -> None:
    appointment = booking(status=AppointmentStatus.CONFIRMED)
    assert remind(service, appointment) == 1
    to, subject, body = sent.call_args.args
    assert to == "maria@example.com"
    assert subject == "Lembrete de agendamento - Studio Bela"
    assert "Serviço: Corte" in body
    assert "Profissional: Ana" in body
    assert "Data: segunda-feira, 09/11/2026" in body
    assert "Horário: 10:00" in body
    assert appointment.reminder_sent_at == now


def test_reminders_are_looked_up_inside_the_configured_window(
    service: AppointmentService, sent: Mock
) -> None:
    remind(service, batch_size=7)
    service.repository.list_due_reminders.assert_called_once_with(
        now=now, until=now + LEAD, limit=7
    )
    sent.assert_not_called()


def test_reminder_is_marked_before_it_is_sent(
    service: AppointmentService, sent: Mock
) -> None:
    appointment = booking(status=AppointmentStatus.CONFIRMED)
    marked_when_sent = []
    sent.side_effect = lambda *args: (
        marked_when_sent.append(appointment.reminder_sent_at) or True
    )
    order = Mock()
    order.attach_mock(service.session.commit, "commit")
    order.attach_mock(sent, "send")
    remind(service, appointment)
    assert [call[0] for call in order.mock_calls] == ["commit", "send"]
    assert marked_when_sent == [now]


def test_failed_reminder_is_unmarked_so_the_next_run_retries(
    service: AppointmentService, sent: Mock
) -> None:
    sent.side_effect = [False, True]
    failed = booking(status=AppointmentStatus.CONFIRMED)
    delivered = booking(status=AppointmentStatus.CONFIRMED, customer_name="Ana Lima")
    assert remind(service, failed, delivered) == 1
    assert failed.reminder_sent_at is None
    assert delivered.reminder_sent_at == now
    assert service.session.commit.call_count == 2


def test_reminders_do_not_touch_confirmation_state(
    service: AppointmentService, sent: Mock
) -> None:
    appointment = booking(status=AppointmentStatus.CONFIRMED)
    remind(service, appointment)
    assert appointment.status == AppointmentStatus.CONFIRMED
    service.session.rollback.assert_not_called()


def test_reminder_migration_adds_the_column_on_top_of_the_history() -> None:
    from io import StringIO

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("c5b8e1a47d93")
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
    assert "ALTER TABLE appointments ADD COLUMN reminder_sent_at TIMESTAMP WITH TIME ZONE" in sql
    assert "DROP" not in sql
