"""US-035 — Profissional visualizar sua agenda.

Cenário: Visualizar agenda
  Dado que estou cadastrado como profissional
  E existem agendamentos associados a mim
  Quando acesso minha agenda
  Então devo visualizar meus atendimentos
  E não devo visualizar informações que não tenho permissão para acessar
"""

# The fixtures come from test_professional_agenda; pytest injects them by name.
# ruff: noqa: F811

from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from test_professional_agenda import (  # noqa: F401
    business_id,
    client,
    colleague_id,
    database,
    owner,
    professional,
    professional_id,
    service_id,
    starts_at,
)

from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
)

week = {
    "starts_at": (starts_at - timedelta(days=1)).isoformat(),
    "ends_at": (starts_at + timedelta(days=6)).isoformat(),
}


def add_booking(
    engine: Engine,
    *,
    professional: UUID,
    hours_after: int,
    customer: str,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
) -> UUID:
    with Session(engine) as session:
        booking = Appointment(
            business_id=business_id,
            professional_id=professional,
            service_id=service_id,
            starts_at=starts_at + timedelta(hours=hours_after),
            ends_at=starts_at + timedelta(hours=hours_after, minutes=30),
            status=status,
            source=AppointmentSource.ONLINE,
            customer_name=customer,
            customer_phone="5585999999999",
            customer_email=f"{customer.lower()}@cliente.com",
            notes="Primeira vez",
        )
        session.add(booking)
        session.commit()
        return booking.id


def test_cenario_visualizar_agenda(
    client: TestClient, professional: dict[str, str], database: Engine
) -> None:
    # Dado que estou cadastrado como profissional (fixture "professional")
    # E existem agendamentos associados a mim
    second = add_booking(database, professional=professional_id, hours_after=3, customer="Bruna")
    first = add_booking(
        database,
        professional=professional_id,
        hours_after=1,
        customer="Ana",
        status=AppointmentStatus.PENDING,
    )
    block = client.post(
        "/api/v1/me/agenda/blocks",
        json={
            "starts_at": (starts_at + timedelta(hours=5)).isoformat(),
            "ends_at": (starts_at + timedelta(hours=6)).isoformat(),
            "notes": "Almoço",
        },
        headers=professional,
    ).json()

    # Quando acesso minha agenda
    response = client.get("/api/v1/me/agenda", params=week, headers=professional)

    # Então devo visualizar meus atendimentos
    assert response.status_code == 200
    agenda = response.json()
    assert [item["id"] for item in agenda] == [str(first), str(second), block["id"]]
    assert agenda[0]["customer_name"] == "Ana"
    assert agenda[0]["service_name"] == "Corte"
    assert agenda[0]["status"] == "PENDING"
    assert agenda[2]["status"] == "BLOCKED"
    assert agenda[2]["service_name"] is None

    # E não devo visualizar informações que não tenho permissão para acessar
    for item in agenda:
        assert set(item) == {
            "id",
            "starts_at",
            "ends_at",
            "status",
            "service_name",
            "customer_name",
            "notes",
        }
    assert "5585999999999" not in response.text
    assert "@cliente.com" not in response.text


def test_agenda_hides_colleagues_and_cancelled_bookings(
    client: TestClient, professional: dict[str, str], database: Engine
) -> None:
    mine = add_booking(database, professional=professional_id, hours_after=1, customer="Ana")
    add_booking(database, professional=colleague_id, hours_after=1, customer="Carla")
    add_booking(
        database,
        professional=professional_id,
        hours_after=2,
        customer="Duda",
        status=AppointmentStatus.CANCELLED,
    )

    response = client.get("/api/v1/me/agenda", params=week, headers=professional)

    assert [item["id"] for item in response.json()] == [str(mine)]


def test_agenda_only_shows_the_requested_period(
    client: TestClient, professional: dict[str, str], database: Engine
) -> None:
    add_booking(database, professional=professional_id, hours_after=24 * 10, customer="Ana")

    response = client.get("/api/v1/me/agenda", params=week, headers=professional)

    assert response.json() == []


@pytest.mark.parametrize(
    "period",
    [
        {"starts_at": week["ends_at"], "ends_at": week["starts_at"]},
        {
            "starts_at": week["starts_at"],
            "ends_at": (starts_at + timedelta(days=40)).isoformat(),
        },
    ],
)
def test_agenda_rejects_invalid_period(
    client: TestClient, professional: dict[str, str], period: dict[str, str]
) -> None:
    response = client.get("/api/v1/me/agenda", params=period, headers=professional)

    assert response.status_code == 422


def test_owner_does_not_use_professional_agenda(
    client: TestClient, owner: dict[str, str]
) -> None:
    response = client.get("/api/v1/me/agenda", params=week, headers=owner)

    assert response.status_code == 403


def test_agenda_requires_login(client: TestClient) -> None:
    response = client.get("/api/v1/me/agenda", params=week)

    assert response.status_code == 401
