"""US-036 — Profissional bloquear horário.

Cenário: Bloquear horário
  Dado que estou autenticado como profissional
  Quando bloqueio um horário
  Então o horário não deve ficar disponível para novos agendamentos
"""

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from io import StringIO
from pathlib import Path
from sqlite3 import Connection
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

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
    from app.core.security import hash_password
    from app.db.session import get_db
    from app.main import app

from test_appointment_concurrency import postgres_agenda  # noqa: F401

from app.db.base import Base
from app.modules.appointments.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
)
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.models import Professional
from app.modules.services.models import Service
from app.modules.users.models import User

PASSWORD = "senha-de-teste-123"
owner_id, other_owner_id = uuid4(), uuid4()
business_id, other_business_id = uuid4(), uuid4()
professional_id, colleague_id, inactive_id, foreign_id = (uuid4() for _ in range(4))
service_id = uuid4()
starts_at = datetime(2030, 1, 7, 13, tzinfo=UTC)
block_payload = {
    "starts_at": starts_at.isoformat(),
    "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
    "notes": "Consulta médica",
}


@pytest.fixture
def database() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        connection: Connection, record: ConnectionPoolEntry
    ) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    password_hash = hash_password(PASSWORD)
    try:
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine) as session:
            session.add(BusinessCategory(id=1, name="Beleza"))
            session.flush()
            session.add_all(
                Business(
                    id=identifier,
                    name=name,
                    category_id=1,
                    whatsapp="85999999999",
                    service_mode=ServiceMode.PRESENCIAL,
                )
                for identifier, name in (
                    (business_id, "Studio"),
                    (other_business_id, "Outro"),
                )
            )
            session.flush()
            session.add_all(
                [
                    Professional(id=professional_id, business_id=business_id, name="Bia"),
                    Professional(id=colleague_id, business_id=business_id, name="Rafa"),
                    Professional(
                        id=inactive_id,
                        business_id=business_id,
                        name="Saiu",
                        is_active=False,
                    ),
                    Professional(
                        id=foreign_id, business_id=other_business_id, name="Outra"
                    ),
                ]
            )
            session.add(
                Service(
                    id=service_id,
                    business_id=business_id,
                    name="Corte",
                    price=50,
                    duration_minutes=30,
                )
            )
            session.add_all(
                User(
                    id=identifier,
                    name="Dona",
                    email=email,
                    password_hash=password_hash,
                    business_id=owned,
                )
                for identifier, email, owned in (
                    (owner_id, "dona@studio.com", business_id),
                    (other_owner_id, "dona@outro.com", other_business_id),
                )
            )
            session.commit()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def client(database: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        settings, "JWT_SECRET_KEY", SecretStr(secrets.token_urlsafe(64))
    )

    def get_test_db() -> Iterator[Session]:
        with Session(database, autoflush=False, expire_on_commit=True) as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db)


def login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.json()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def grant_access(
    client: TestClient, owner: dict[str, str], professional: UUID, email: str
) -> dict[str, str]:
    response = client.post(
        f"/api/v1/professionals/{professional}/access",
        json={"email": email, "password": PASSWORD},
        headers=owner,
    )
    assert response.status_code == 201, response.json()
    return login(client, email)


@pytest.fixture
def owner(client: TestClient) -> dict[str, str]:
    return login(client, "dona@studio.com")


@pytest.fixture
def professional(client: TestClient, owner: dict[str, str]) -> dict[str, str]:
    return grant_access(client, owner, professional_id, "bia@studio.com")


# --- Acesso criado pelo dono (Figma 04.03, "E-mail de acesso") ---


def test_owner_creates_access_and_professional_logs_in(
    client: TestClient, owner: dict[str, str], database: Engine
) -> None:
    response = client.post(
        f"/api/v1/professionals/{professional_id}/access",
        json={"email": " Bia@Studio.com ", "password": PASSWORD},
        headers=owner,
    )

    assert response.status_code == 201
    assert response.json()["email"] == "bia@studio.com"
    assert response.json()["professional_id"] == str(professional_id)
    with Session(database) as session:
        user = session.scalar(select(User).where(User.email == "bia@studio.com"))
        assert user.professional_id == professional_id
        assert user.business_id is None
        assert user.password_hash != PASSWORD
    login(client, "bia@studio.com")


@pytest.mark.parametrize(
    "target, email, expected",
    [
        (professional_id, "dona@studio.com", 409),  # e-mail já usado
        (inactive_id, "saiu@studio.com", 422),  # profissional desativado
        (foreign_id, "outra@studio.com", 404),  # profissional de outro negócio
        (uuid4(), "nao@existe.com", 404),
    ],
)
def test_owner_cannot_create_invalid_access(
    client: TestClient,
    owner: dict[str, str],
    target: UUID,
    email: str,
    expected: int,
) -> None:
    response = client.post(
        f"/api/v1/professionals/{target}/access",
        json={"email": email, "password": PASSWORD},
        headers=owner,
    )

    assert response.status_code == expected


def test_professional_gets_only_one_access(
    client: TestClient, owner: dict[str, str], professional: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/professionals/{professional_id}/access",
        json={"email": "outro@studio.com", "password": PASSWORD},
        headers=owner,
    )

    assert response.status_code == 409


def test_only_the_owner_creates_access(
    client: TestClient, professional: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/professionals/{colleague_id}/access",
        json={"email": "rafa@studio.com", "password": PASSWORD},
        headers=professional,
    )

    assert response.status_code == 403


# --- Bloqueio pelo profissional ---


def test_professional_blocks_own_agenda(
    client: TestClient, professional: dict[str, str], database: Engine
) -> None:
    response = client.post(
        "/api/v1/me/agenda/blocks", json=block_payload, headers=professional
    )

    assert response.status_code == 201
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["professional_id"] == str(professional_id)
    assert response.json()["business_id"] == str(business_id)


def test_professional_cannot_block_someone_else(
    client: TestClient, professional: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/me/agenda/blocks",
        json={**block_payload, "professional_id": str(colleague_id)},
        headers=professional,
    )

    assert response.status_code == 422


def test_block_over_existing_booking_is_refused(
    client: TestClient, professional: dict[str, str], database: Engine
) -> None:
    client.post("/api/v1/me/agenda/blocks", json=block_payload, headers=professional)

    response = client.post(
        "/api/v1/me/agenda/blocks", json=block_payload, headers=professional
    )

    assert response.status_code == 409


def test_block_needs_end_after_start(
    client: TestClient, professional: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/me/agenda/blocks",
        json={**block_payload, "ends_at": block_payload["starts_at"]},
        headers=professional,
    )

    assert response.status_code == 422


def test_professional_lists_only_own_blocks(
    client: TestClient,
    owner: dict[str, str],
    professional: dict[str, str],
) -> None:
    client.post("/api/v1/me/agenda/blocks", json=block_payload, headers=professional)
    colleague = grant_access(client, owner, colleague_id, "rafa@studio.com")
    client.post(
        "/api/v1/me/agenda/blocks",
        json={**block_payload, "notes": "Bloqueio da Rafa"},
        headers=colleague,
    )

    response = client.get(
        "/api/v1/me/agenda/blocks",
        params={
            "starts_at": (starts_at - timedelta(days=1)).isoformat(),
            "ends_at": (starts_at + timedelta(days=1)).isoformat(),
        },
        headers=professional,
    )

    assert response.status_code == 200
    assert [block["notes"] for block in response.json()] == ["Consulta médica"]


def test_professional_cancels_own_block(
    client: TestClient, professional: dict[str, str], database: Engine
) -> None:
    block = client.post(
        "/api/v1/me/agenda/blocks", json=block_payload, headers=professional
    ).json()

    response = client.delete(
        f"/api/v1/me/agenda/blocks/{block['id']}", headers=professional
    )

    assert response.status_code == 204
    with Session(database) as session:
        assert session.get(Appointment, UUID(block["id"])) is None


def test_professional_cannot_cancel_bookings_or_colleague_blocks(
    client: TestClient,
    owner: dict[str, str],
    professional: dict[str, str],
    database: Engine,
) -> None:
    colleague = grant_access(client, owner, colleague_id, "rafa@studio.com")
    colleague_block = client.post(
        "/api/v1/me/agenda/blocks", json=block_payload, headers=colleague
    ).json()
    with Session(database) as session:
        booking = Appointment(
            business_id=business_id,
            professional_id=professional_id,
            service_id=service_id,
            starts_at=starts_at + timedelta(days=1),
            ends_at=starts_at + timedelta(days=1, hours=1),
            status=AppointmentStatus.PENDING,
            source=AppointmentSource.ONLINE,
            customer_name="Cliente",
            customer_phone="5585999999999",
        )
        session.add(booking)
        session.commit()
        booking_id = booking.id

    for appointment_id in (colleague_block["id"], booking_id):
        response = client.delete(
            f"/api/v1/me/agenda/blocks/{appointment_id}", headers=professional
        )
        assert response.status_code == 404


# --- O profissional só enxerga a própria agenda ---


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/api/v1/businesses"),
        ("get", "/api/v1/professionals"),
        ("get", "/api/v1/financial/summary?start_date=2030-01-01&end_date=2030-01-31"),
        ("post", "/api/v1/appointments/blocks"),
    ],
)
def test_professional_cannot_use_owner_routes(
    client: TestClient, professional: dict[str, str], method: str, path: str
) -> None:
    response = getattr(client, method)(path, headers=professional)

    assert response.status_code == 403


def test_professional_cannot_create_a_business(
    client: TestClient, professional: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/businesses",
        json={
            "name": "Meu negócio",
            "category_id": 1,
            "whatsapp": "85999999999",
            "service_mode": "PRESENCIAL",
        },
        headers=professional,
    )

    assert response.status_code == 409


def test_owner_cannot_use_professional_agenda(
    client: TestClient, owner: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/me/agenda/blocks", json=block_payload, headers=owner
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "User is not a professional"}


def test_deactivating_the_professional_turns_off_the_login(
    client: TestClient, owner: dict[str, str], professional: dict[str, str]
) -> None:
    client.delete(f"/api/v1/professionals/{professional_id}", headers=owner)

    response = client.post(
        "/api/v1/me/agenda/blocks", json=block_payload, headers=professional
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Professional access is disabled"}


def test_agenda_requires_login(client: TestClient) -> None:
    response = client.post("/api/v1/me/agenda/blocks", json=block_payload)

    assert response.status_code == 401


# --- Cenário completo, com PostgreSQL real (opcional: TEST_POSTGRES_URL) ---


def test_cenario_bloquear_horario(
    postgres_agenda,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, pg_business, pg_service, pg_professional, _, start = postgres_agenda
    monkeypatch.setattr(
        settings, "JWT_SECRET_KEY", SecretStr(secrets.token_urlsafe(64))
    )
    with Session(engine) as session:
        session.add(
            User(
                name="Dona",
                email="dona@teste.com",
                password_hash=hash_password(PASSWORD),
                business_id=pg_business,
            )
        )
        session.commit()

    def get_test_db() -> Iterator[Session]:
        with Session(engine, autoflush=False, expire_on_commit=True) as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app) as client:
            tz = ZoneInfo(settings.BUSINESS_TIMEZONE)
            day = start.astimezone(tz).date()
            availability = {
                "service_id": str(pg_service),
                "professional_id": str(pg_professional),
                "date": day.isoformat(),
            }
            free_path = f"/api/v1/public/businesses/{pg_business}/availability"
            free_before = client.get(free_path, params=availability).json()
            blocked_start = datetime.combine(day, time(10), tz)
            assert blocked_start.isoformat() in free_before

            # Dado que estou autenticado como profissional
            owner = login(client, "dona@teste.com")
            professional = grant_access(
                client, owner, pg_professional, "profissional@teste.com"
            )

            # Quando bloqueio um horário
            response = client.post(
                "/api/v1/me/agenda/blocks",
                json={
                    "starts_at": blocked_start.isoformat(),
                    "ends_at": (blocked_start + timedelta(hours=1)).isoformat(),
                },
                headers=professional,
            )
            assert response.status_code == 201

            # Então o horário não deve ficar disponível para novos agendamentos
            free_after = client.get(free_path, params=availability).json()
            assert blocked_start.isoformat() not in free_after
            assert (blocked_start + timedelta(minutes=30)).isoformat() not in free_after
            assert set(free_after) < set(free_before)

            booking = client.post(
                f"/api/v1/public/businesses/{pg_business}/appointments",
                json={
                    "service_id": str(pg_service),
                    "professional_id": str(pg_professional),
                    "starts_at": blocked_start.isoformat(),
                    "customer_name": "Cliente Teste",
                    "customer_phone": "85999999999",
                },
            )
            assert booking.status_code == 409

            # Ao desfazer o bloqueio, o horário volta
            client.delete(
                f"/api/v1/me/agenda/blocks/{response.json()['id']}",
                headers=professional,
            )
            free_again = client.get(free_path, params=availability).json()
            assert blocked_start.isoformat() in free_again
    finally:
        app.dependency_overrides.pop(get_db)


def test_migration_links_users_to_professionals() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("4d8e2b7c1a95")
    assert revision.down_revision == "9b72e4f1a603"
    assert scripts.get_current_head() == "4d8e2b7c1a95"

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()

    assert "ADD COLUMN professional_id UUID" in sql
    assert "FOREIGN KEY(professional_id) REFERENCES professionals (id)" in sql
    assert "CONSTRAINT uq_users_professional_id UNIQUE (professional_id)" in sql
    assert (
        "CONSTRAINT ck_users_single_role CHECK "
        "(business_id IS NULL OR professional_id IS NULL)" in sql
    )
