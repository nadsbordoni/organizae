from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session
from test_assistant_tools import mock_conversation
from test_clients import (
    auth_headers,
    business_a,
    business_b,
    client,
    client_a,
    database,
    inactive_user,
    other_client,
    owner_b,
    password_hash,
    professional_a,
    professional_b,
    service_a,
    service_b,
    unassigned_user,
)

from app.core.config import settings
from app.main import app
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    BusinessHour,
)
from app.modules.appointments.repository import AppointmentRepository
from app.modules.assistant.actions import action_repository
from app.modules.assistant.models import AssistantMessage
from app.modules.assistant.providers.base import ProviderReply, ToolCall
from app.modules.assistant.router import get_assistant_provider
from app.modules.clients.models import Client
from app.modules.professionals.models import Professional
from app.modules.services.associations import professional_services
from app.modules.services.models import Service

__all__ = ["client", "database", "password_hash"]
starts_at = datetime.combine(
    datetime.now(UTC).date() + timedelta(days=2), time(10), UTC
)


@pytest.fixture(autouse=True)
def agenda(database, monkeypatch):
    action_repository.actions.clear()
    action_repository.requests.clear()
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    monkeypatch.setattr(settings, "BUSINESS_TIMEZONE", "UTC")
    with Session(database) as session:
        session.add_all(
            BusinessHour(
                business_id=business_id,
                weekday=starts_at.weekday(),
                opens_at=time(9),
                closes_at=time(12),
            )
            for business_id in (business_a, business_b)
        )
        session.execute(
            insert(professional_services),
            [
                {
                    "professional_id": professional_id,
                    "service_id": service_id,
                    "business_id": business_id,
                }
                for professional_id, service_id, business_id in (
                    (professional_a, service_a, business_a),
                    (professional_b, service_b, business_b),
                )
            ],
        )
        session.commit()

    original = AppointmentRepository.list_busy

    def sqlite_busy(self, **kwargs):
        # SQLite discards offsets; this fixture stores all timestamps in UTC.
        return [
            (start.replace(tzinfo=UTC), end.replace(tzinfo=UTC))
            for start, end in original(self, **kwargs)
        ]

    monkeypatch.setattr(AppointmentRepository, "list_busy", sqlite_busy)
    yield
    action_repository.actions.clear()
    action_repository.requests.clear()
    app.dependency_overrides.pop(get_assistant_provider, None)


def chat_tool(client, name, arguments, **data):
    provider, conversation = mock_conversation(
        [
            ProviderReply(calls=[ToolCall(name, arguments)]),
            ProviderReply(text="Consulta concluída."),
        ]
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    response = client.post(
        "/api/v1/assistant/chat",
        headers=auth_headers(),
        json={"message": "Consulte a agenda", **data},
    )
    return response, conversation


def booking_arguments(**changes):
    return {
        "client_id": str(client_a),
        "service_id": str(service_a),
        "professional_id": str(professional_a),
        "starts_at": starts_at.isoformat(),
        **changes,
    }


def prepare(client, **changes):
    response, _ = chat_tool(client, "create_appointment", booking_arguments(**changes))
    assert response.status_code == 200, response.text
    return response.json()["pending_actions"][0]["id"]


def decide(client, action_id, decision="confirm", user_headers=None):
    return client.post(
        f"/api/v1/assistant/actions/{action_id}/{decision}",
        headers=user_headers or auth_headers(),
        **({"json": {"decision": decision}} if decision == "confirm" else {}),
    )


def seed_appointment(database, **changes):
    with Session(database) as session:
        appointment = Appointment(
            **{
                "business_id": business_a,
                "service_id": service_a,
                "professional_id": professional_a,
                "customer_name": "Alice",
                "customer_phone": "85999999999",
                "starts_at": starts_at,
                "ends_at": starts_at + timedelta(minutes=30),
                "status": AppointmentStatus.PENDING,
                "source": AppointmentSource.PANEL,
                **changes,
            }
        )
        session.add(appointment)
        session.commit()
        return appointment.id


def appointment_count(database):
    with Session(database) as session:
        return session.scalar(select(func.count()).select_from(Appointment))


def period(**changes):
    return {
        "starts_at": starts_at.replace(hour=0).isoformat(),
        "ends_at": (starts_at.replace(hour=0) + timedelta(days=1)).isoformat(),
        **changes,
    }


def test_list_filters_pagination_tenant_and_minimal_projection(client, database):
    first = seed_appointment(database)
    seed_appointment(
        database,
        starts_at=starts_at + timedelta(hours=1),
        ends_at=starts_at + timedelta(hours=1, minutes=30),
    )
    seed_appointment(database, status=AppointmentStatus.CANCELLED)
    foreign = seed_appointment(
        database,
        business_id=business_b,
        service_id=service_b,
        professional_id=professional_b,
    )
    response, conversation = chat_tool(
        client,
        "list_appointments",
        period(limit=1, status="PENDING", customer_phone="(85) 99999-9999"),
    )
    assert response.status_code == 200
    result = conversation.generate.call_args.args[0][0].response
    assert result["has_more"] is True
    assert [item["id"] for item in result["items"]] == [str(first)]
    assert (
        not {"business_id", "customer_phone", "customer_email", "notes"}
        & result["items"][0].keys()
    )
    response, conversation = chat_tool(
        client, "list_appointments", period(limit=1, offset=1, status="PENDING")
    )
    page = conversation.generate.call_args.args[0][0].response
    assert len(page["items"]) == 1 and page["has_more"] is False
    assert page["items"][0]["id"] not in (str(first), str(foreign))
    for field, value in (
        ("professional_id", professional_b),
        ("service_id", service_b),
    ):
        _, conversation = chat_tool(
            client, "list_appointments", period(**{field: str(value)})
        )
        assert conversation.generate.call_args.args[0][0].response["items"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"business_id": str(business_b)},
        {"ends_at": (starts_at + timedelta(days=32)).isoformat()},
        {"ends_at": starts_at.replace(hour=0).isoformat()},
        {"starts_at": "2026-11-01T10:00:00"},
        {"limit": 51},
        {"limit": True},
        {"offset": -1},
    ],
)
def test_list_rejects_unbounded_or_untrusted_arguments(client, database, changes):
    response, _ = chat_tool(client, "list_appointments", period(**changes))
    assert response.status_code == 502
    assert appointment_count(database) == 0


def test_availability_is_actual_bounded_and_not_a_reservation(client, database):
    seed_appointment(database)
    _, conversation = chat_tool(
        client,
        "check_availability",
        {
            "service_id": str(service_a),
            "professional_id": str(professional_a),
            "day": starts_at.date().isoformat(),
            "limit": 2,
        },
    )
    result = conversation.generate.call_args.args[0][0].response
    assert result["slots"] == [
        starts_at.replace(hour=9).isoformat(),
        starts_at.replace(hour=9, minute=30).isoformat(),
    ]
    assert result["has_more"] is True
    assert result["timezone"] == "UTC"
    assert appointment_count(database) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"service_id": str(service_b)},
        {"professional_id": str(professional_b)},
        {"service_id": str(uuid4())},
    ],
)
def test_availability_rejects_foreign_and_unknown_ids(client, changes):
    response, conversation = chat_tool(
        client,
        "check_availability",
        {
            "service_id": str(service_a),
            "professional_id": str(professional_a),
            "day": starts_at.date().isoformat(),
            **changes,
        },
    )
    assert response.status_code == 200
    assert "error" in conversation.generate.call_args.args[0][0].response


def test_availability_honors_general_blocks_and_booking_window(client, database):
    seed_appointment(
        database,
        service_id=None,
        professional_id=None,
        customer_name=None,
        customer_phone=None,
        status=AppointmentStatus.BLOCKED,
        starts_at=starts_at.replace(hour=9),
        ends_at=starts_at.replace(hour=12),
    )
    for day in (starts_at.date(), (starts_at + timedelta(days=121)).date()):
        _, conversation = chat_tool(
            client,
            "check_availability",
            {
                "service_id": str(service_a),
                "professional_id": str(professional_a),
                "day": day.isoformat(),
            },
        )
        assert conversation.generate.call_args.args[0][0].response["slots"] == []


def test_confirmation_creates_once_with_existing_client_and_saved_arguments(
    client, database
):
    action_id = prepare(client)
    assert appointment_count(database) == 0
    assert decide(client, action_id).status_code == 200
    assert decide(client, action_id).status_code == 409
    with Session(database) as session:
        appointment = session.scalar(select(Appointment))
        assert appointment.business_id == business_a
        assert appointment.status == AppointmentStatus.PENDING
        assert appointment.source == AppointmentSource.PANEL
        assert appointment.customer_name == "Alice"
        assert appointment.customer_phone == "85999999999"
        assert (
            appointment.service_id == service_a
            and appointment.professional_id == professional_a
        )
        assert session.scalar(select(func.count()).select_from(Client)) == 3
    assert appointment_count(database) == 1


def test_pending_preview_and_conversation_history_are_preserved(client, database):
    response, _ = chat_tool(client, "create_appointment", booking_arguments())
    pending = response.json()["pending_actions"][0]
    assert pending["preview"]["customer_name"] == "Alice"
    assert pending["preview"]["service_name"] == "Haircut"
    conversation_id = response.json()["conversation_id"]
    with Session(database) as session:
        messages = session.scalars(
            select(AssistantMessage).where(
                AssistantMessage.conversation_id == UUID(conversation_id)
            )
        ).all()
        assert len(messages) == 2
    chat_tool(client, "list_appointments", period(), conversation_id=conversation_id)
    assert appointment_count(database) == 0


@pytest.mark.parametrize("state", ["cancelled", "expired"])
def test_cancelled_or_expired_actions_never_create_and_cannot_be_reused(
    client, database, state
):
    action_id = prepare(client)
    if state == "cancelled":
        assert decide(client, action_id, "cancel").json()["state"] == state
    else:
        action_repository.actions[UUID(action_id)].expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    assert decide(client, action_id).status_code == 409
    assert appointment_count(database) == 0


def test_two_pending_actions_do_not_reserve_and_second_confirmation_conflicts(
    client, database
):
    first, second = prepare(client), prepare(client)
    assert decide(client, first).status_code == 200
    response = decide(client, second)
    assert response.status_code == 409
    assert response.json()["code"] == "assistant_appointment_conflict"
    assert "horário" in response.json()["detail"]
    assert decide(client, second).status_code == 409
    assert action_repository.actions[UUID(second)].state == "failed"
    assert appointment_count(database) == 1


@pytest.mark.parametrize(
    "change", ["service", "professional", "association", "hours", "block", "client"]
)
def test_confirmation_revalidates_changed_business_rules(client, database, change):
    action_id = prepare(client)
    with Session(database) as session:
        if change == "service":
            session.get(Service, service_a).is_active = False
        elif change == "professional":
            session.get(Professional, professional_a).is_active = False
        elif change == "association":
            session.execute(
                delete(professional_services).where(
                    professional_services.c.professional_id == professional_a
                )
            )
        elif change == "hours":
            session.execute(delete(BusinessHour))
        elif change == "client":
            session.delete(session.get(Client, client_a))
        session.commit()
    if change == "block":
        block = client.post(
            "/api/v1/appointments/blocks",
            headers=auth_headers(),
            json={
                "starts_at": starts_at.isoformat(),
                "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
            },
        )
        assert block.status_code == 201
    response = decide(client, action_id)
    assert response.status_code in (409, 422)
    with Session(database) as session:
        assert (
            session.scalar(
                select(func.count()).where(
                    Appointment.status != AppointmentStatus.BLOCKED
                )
            )
            == 0
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"client_id": str(other_client)},
        {"service_id": str(service_b)},
        {"professional_id": str(professional_b)},
        {"client_id": str(uuid4())},
        {"starts_at": starts_at.replace(minute=15).isoformat()},
        {"business_id": str(business_b)},
        {"status": "CONFIRMED"},
        {"source": "ONLINE"},
    ],
)
def test_invalid_creations_are_not_prepared_or_written(client, database, changes):
    response, conversation = chat_tool(
        client, "create_appointment", booking_arguments(**changes)
    )
    assert response.status_code == 200
    assert not response.json().get("pending_actions")
    assert "error" in conversation.generate.call_args.args[0][0].response
    assert appointment_count(database) == 0


def test_client_ambiguity_requires_explicit_client_id_and_does_not_create_client(
    client, database
):
    with Session(database) as session:
        session.add(Client(business_id=business_a, name="Alice", phone="85988888888"))
        session.commit()
    _, conversation = chat_tool(client, "list_clients", {"search": "Alice"})
    assert len(conversation.generate.call_args.args[0][0].response["items"]) == 2
    args = booking_arguments()
    args.pop("client_id")
    args["customer_name"] = "Alice"
    response, _ = chat_tool(client, "create_appointment", args)
    assert not response.json().get("pending_actions")
    assert not action_repository.actions
    assert appointment_count(database) == 0


def test_different_owner_cannot_confirm_and_arguments_cannot_be_replaced(
    client, database
):
    action_id = prepare(client)
    assert (
        decide(client, action_id, user_headers=auth_headers(owner_b)).status_code == 409
    )
    response = client.post(
        f"/api/v1/assistant/actions/{action_id}/confirm",
        headers=auth_headers(),
        json={
            "decision": "confirm",
            "business_id": str(business_b),
        },
    )
    assert response.status_code == 422
    assert appointment_count(database) == 0
    assert decide(client, action_id).status_code == 200


@pytest.mark.parametrize(
    "user_id,status", [(None, 401), (inactive_user, 401), (unassigned_user, 403)]
)
def test_agenda_tools_require_authenticated_active_business_user(
    client, user_id, status
):
    response = client.post(
        "/api/v1/assistant/chat",
        headers=auth_headers(user_id) if user_id else {},
        json={"message": "Agenda"},
    )
    assert response.status_code == status


def test_no_booking_without_explicit_confirmation_even_when_message_says_yes(
    client, database
):
    action_id = prepare(client)
    provider, _ = mock_conversation(
        [ProviderReply(text="Confirme a ação pelo identificador.")]
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    response = client.post(
        "/api/v1/assistant/chat",
        headers=auth_headers(),
        json={"message": "sim, confirme"},
    )
    assert response.status_code == 200
    assert action_repository.actions[UUID(action_id)].state == "pending"
    assert appointment_count(database) == 0


def test_writes_stay_disabled_by_existing_environment_gate(
    client, monkeypatch, database
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    response, _ = chat_tool(client, "create_appointment", booking_arguments())
    assert response.status_code == 403
    assert appointment_count(database) == 0


def test_commit_failure_rolls_back_and_action_cannot_be_retried(client, database):
    action_id = prepare(client)
    with patch.object(Session, "commit", side_effect=RuntimeError("private")):
        response = decide(client, action_id)
    assert response.status_code == 500
    assert "private" not in response.text
    assert appointment_count(database) == 0
    assert decide(client, action_id).status_code == 409


@pytest.mark.parametrize("professional", [None, professional_a])
def test_block_cannot_overlap_existing_appointment(client, database, professional):
    seed_appointment(database)
    response = client.post(
        "/api/v1/appointments/blocks",
        headers=auth_headers(),
        json={
            "professional_id": str(professional) if professional else None,
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 409
    assert appointment_count(database) == 1


def test_block_cancellation_limit_is_not_bypassed_and_still_blocks_availability(
    client, database
):
    block_id = seed_appointment(
        database,
        service_id=None,
        professional_id=None,
        customer_name=None,
        customer_phone=None,
        status=AppointmentStatus.BLOCKED,
    )
    response = client.patch(
        f"/api/v1/appointments/{block_id}/status",
        headers=auth_headers(),
        json={"status": "CANCELLED"},
    )
    assert response.status_code == 409
    _, conversation = chat_tool(
        client,
        "check_availability",
        {
            "service_id": str(service_a),
            "professional_id": str(professional_a),
            "day": starts_at.date().isoformat(),
        },
    )
    assert (
        starts_at.isoformat()
        not in conversation.generate.call_args.args[0][0].response["slots"]
    )
    with Session(database) as session:
        assert session.get(Appointment, block_id).status == AppointmentStatus.BLOCKED
