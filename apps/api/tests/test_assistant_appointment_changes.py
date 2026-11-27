from datetime import UTC, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value
from test_assistant_appointments import (
    agenda,
    chat_tool,
    decide,
    seed_appointment,
    starts_at,
)
from test_clients import (
    business_b,
    client,
    database,
    password_hash,
    professional_a,
    professional_b,
    service_a,
    service_b,
)

from app.modules.appointments.models import Appointment, AppointmentStatus
from app.modules.appointments.repository import AppointmentRepository

__all__ = ["agenda", "client", "database", "password_hash"]
new_time = starts_at + timedelta(hours=1)


@pytest.fixture(autouse=True)
def aware_appointments(monkeypatch):
    original = AppointmentRepository.get_by_id

    def sqlite_get_by_id(self, *args, **kwargs):
        # SQLite discards offsets; this fixture stores all timestamps in UTC.
        appointment = original(self, *args, **kwargs)
        if appointment is not None and appointment.starts_at.tzinfo is None:
            for field in ("starts_at", "ends_at"):
                value = getattr(appointment, field).replace(tzinfo=UTC)
                set_committed_value(appointment, field, value)
        return appointment

    monkeypatch.setattr(AppointmentRepository, "get_by_id", sqlite_get_by_id)


def prepare_change(client, name, arguments):
    response, conversation = chat_tool(client, name, arguments)
    assert response.status_code == 200, response.text
    pending = response.json().get("pending_actions") or []
    if pending:
        # A pending action ends the turn before results return to the model.
        return pending, None
    return pending, conversation.generate.call_args.args[0][0].response


def stored(database, appointment_id):
    with Session(database) as session:
        appointment = session.get(Appointment, appointment_id)
        session.expunge(appointment)
        return appointment


def available_slots(client):
    _, conversation = chat_tool(
        client,
        "check_availability",
        {
            "service_id": str(service_a),
            "professional_id": str(professional_a),
            "day": starts_at.date().isoformat(),
        },
    )
    return conversation.generate.call_args.args[0][0].response["slots"]


def reschedule_arguments(appointment_id):
    return {"record_id": str(appointment_id), "starts_at": new_time.isoformat()}


def test_reschedule_moves_the_booking_only_after_confirmation(client, database):
    appointment_id = seed_appointment(database, status=AppointmentStatus.CONFIRMED)
    pending, _ = prepare_change(
        client, "reschedule_appointment", reschedule_arguments(appointment_id)
    )
    preview = pending[0]["preview"]
    assert preview["customer_name"] == "Alice"
    assert preview["current_starts_at"] == starts_at.isoformat()
    assert preview["starts_at"] == new_time.isoformat()
    assert stored(database, appointment_id).starts_at.hour == starts_at.hour

    assert decide(client, pending[0]["id"]).status_code == 200
    appointment = stored(database, appointment_id)
    assert appointment.starts_at.replace(tzinfo=UTC) == new_time
    assert appointment.ends_at.replace(tzinfo=UTC) == new_time + timedelta(minutes=30)
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert starts_at.isoformat() in available_slots(client)
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1


def test_reschedule_refuses_a_taken_time_without_pending_action(client, database):
    appointment_id = seed_appointment(database)
    seed_appointment(
        database, starts_at=new_time, ends_at=new_time + timedelta(minutes=30)
    )
    pending, result = prepare_change(
        client, "reschedule_appointment", reschedule_arguments(appointment_id)
    )
    assert pending == []
    assert "Alteração recusada" in result["error"]


def test_confirmation_revalidates_a_time_taken_after_the_preview(client, database):
    appointment_id = seed_appointment(database)
    pending, _ = prepare_change(
        client, "reschedule_appointment", reschedule_arguments(appointment_id)
    )
    seed_appointment(
        database, starts_at=new_time, ends_at=new_time + timedelta(minutes=30)
    )
    assert decide(client, pending[0]["id"]).status_code == 409
    assert stored(database, appointment_id).starts_at.hour == starts_at.hour


def test_update_changes_only_the_informed_fields(client, database):
    appointment_id = seed_appointment(database, notes="antiga")
    pending, _ = prepare_change(
        client,
        "update_appointment",
        {"record_id": str(appointment_id), "data": {"notes": "Trazer exames"}},
    )
    assert pending[0]["preview"]["notes"] == "Trazer exames"
    assert "starts_at" not in pending[0]["preview"]
    assert decide(client, pending[0]["id"]).status_code == 200
    appointment = stored(database, appointment_id)
    assert appointment.notes == "Trazer exames"
    assert appointment.starts_at.replace(tzinfo=UTC) == starts_at


def test_update_can_move_the_time_with_other_fields(client, database):
    appointment_id = seed_appointment(database)
    pending, _ = prepare_change(
        client,
        "update_appointment",
        {
            "record_id": str(appointment_id),
            "data": {"starts_at": new_time.isoformat(), "notes": "Remarcado"},
        },
    )
    assert decide(client, pending[0]["id"]).status_code == 200
    appointment = stored(database, appointment_id)
    assert appointment.starts_at.replace(tzinfo=UTC) == new_time
    assert appointment.notes == "Remarcado"


@pytest.mark.parametrize(
    "data", [{}, {"starts_at": None}, {"service_id": None}, {"price": 10}]
)
def test_update_requires_valid_changes(client, database, data):
    appointment_id = seed_appointment(database)
    pending, result = prepare_change(
        client, "update_appointment", {"record_id": str(appointment_id), "data": data}
    )
    assert pending == []
    assert "error" in result


def test_cancel_frees_the_time_and_cannot_be_repeated(client, database):
    appointment_id = seed_appointment(database)
    arguments = {"record_id": str(appointment_id)}
    pending, _ = prepare_change(client, "cancel_appointment", arguments)
    assert pending[0]["preview"]["customer_name"] == "Alice"
    assert stored(database, appointment_id).status == AppointmentStatus.PENDING
    assert starts_at.isoformat() not in available_slots(client)

    assert decide(client, pending[0]["id"]).status_code == 200
    assert stored(database, appointment_id).status == AppointmentStatus.CANCELLED
    assert starts_at.isoformat() in available_slots(client)

    pending, result = prepare_change(client, "cancel_appointment", arguments)
    assert pending == [] and "Alteração recusada" in result["error"]


def test_declining_the_action_keeps_the_appointment(client, database):
    appointment_id = seed_appointment(database)
    pending, _ = prepare_change(
        client, "cancel_appointment", {"record_id": str(appointment_id)}
    )
    assert decide(client, pending[0]["id"], "cancel").status_code == 200
    assert stored(database, appointment_id).status == AppointmentStatus.PENDING


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("reschedule_appointment", {"starts_at": new_time.isoformat()}),
        ("update_appointment", {"data": {"notes": "x"}}),
        ("cancel_appointment", {}),
    ],
)
def test_appointments_of_other_businesses_are_not_found(
    client, database, name, arguments
):
    foreign_id = seed_appointment(
        database,
        business_id=business_b,
        service_id=service_b,
        professional_id=professional_b,
    )
    pending, result = prepare_change(
        client, name, {"record_id": str(foreign_id), **arguments}
    )
    assert pending == []
    assert "não encontrado" in result["error"]
    assert stored(database, foreign_id).status == AppointmentStatus.PENDING


@pytest.mark.parametrize("state", ["blocked", "started"])
def test_blocks_and_started_appointments_cannot_be_moved(client, database, state):
    if state == "blocked":
        appointment_id = seed_appointment(
            database,
            service_id=None,
            professional_id=None,
            customer_name=None,
            customer_phone=None,
            status=AppointmentStatus.BLOCKED,
        )
    else:
        past = starts_at - timedelta(days=3)
        appointment_id = seed_appointment(
            database, starts_at=past, ends_at=past + timedelta(minutes=30)
        )
    pending, result = prepare_change(
        client, "reschedule_appointment", reschedule_arguments(appointment_id)
    )
    assert pending == []
    assert "Alteração recusada" in result["error"]
