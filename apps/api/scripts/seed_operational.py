"""Manual operational fixtures, isolated from financial seeds and migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.appointments.exceptions import AppointmentError
from app.modules.appointments.models import Appointment, AppointmentStatus, BusinessHour
from app.modules.appointments.schemas import (
    AppointmentStatusUpdate,
    BlockCreateRequest,
    BusinessHoursUpdate,
    OnlineBookingRequest,
)
from app.modules.appointments.service import BOOKING_WINDOW, AppointmentService
from app.modules.businesses.exceptions import BusinessError
from app.modules.businesses.models import Business
from app.modules.categories.exceptions import CategoryError
from app.modules.categories.models import Category
from app.modules.categories.schemas import CategoryCreate
from app.modules.categories.service import CategoryService
from app.modules.clients.exceptions import ClientError
from app.modules.clients.models import Client
from app.modules.clients.schemas import ClientCreate
from app.modules.clients.service import ClientService
from app.modules.professionals.exceptions import ProfessionalError
from app.modules.professionals.models import Professional
from app.modules.professionals.schemas import ProfessionalCreate
from app.modules.professionals.service import ProfessionalService
from app.modules.services.associations import professional_services
from app.modules.services.exceptions import ServiceError
from app.modules.services.models import Service
from app.modules.services.schemas import ServiceCreate, ServiceUpdate
from app.modules.services.service import ServiceService

MARKER = "[SEED-OPS-V1]"
BOOKING_COUNT = 200
BLOCK_COUNT = 6
SEARCH_DAYS = 60
CATEGORIES = {
    "haircuts": "Cortes",
    "beard": "Barba",
    "treatments": "Tratamentos",
    "combos": "Combos",
}
SERVICES = (
    ("Corte clássico", "35.00", 30, "haircuts"),
    ("Corte degradê", "45.00", 45, "haircuts"),
    ("Corte na tesoura", "50.00", 60, "haircuts"),
    ("Barba expressa", "25.00", 15, "beard"),
    ("Barba completa", "40.00", 30, "beard"),
    ("Corte e barba", "70.00", 60, "combos"),
    ("Hidratação", "30.00", 30, "treatments"),
    ("Pigmentação", "55.00", 45, "treatments"),
    ("Tratamento capilar", "80.00", 90, "treatments"),
    ("Acabamento", "15.00", 15, "haircuts"),
    ("Corte infantil", "30.00", 30, "haircuts"),
    ("Pacote completo", "120.00", 120, "combos"),
)


class SeedError(ValueError):
    pass


def fixture_id(business_id: UUID, key: str) -> UUID:
    digest = hashlib.sha256(
        f"organizae:operational-seed:v1:{business_id}:{key}".encode()
    ).digest()
    return UUID(bytes=digest[:16], version=4)


def metadata(reference: date, tz: ZoneInfo) -> str:
    return f"{MARKER} reference={reference.isoformat()} timezone={tz.key}"


def find_reference(
    session: Session, business_id: UUID, now: datetime, tz: ZoneInfo
) -> date:
    references = set()
    for model in (Client, Appointment):
        notes = session.scalars(
            select(model.notes).where(
                model.business_id == business_id,
                model.notes.startswith(f"{MARKER} reference=", autoescape=True),
            )
        )
        for note in notes:
            match = re.fullmatch(
                re.escape(MARKER)
                + r" reference=(\d{4}-\d{2}-\d{2}) timezone=(\S+)(?: .*)?",
                note,
            )
            if not match or match[2] != tz.key:
                raise SeedError(
                    "Metadados do seed incompatíveis com o fuso atual; nada será substituído."
                )
            references.add(date.fromisoformat(match[1]))
    if len(references) > 1:
        raise SeedError(
            "Há mais de uma data de referência reservada do seed nesta empresa."
        )
    if references:
        reference = references.pop()
        if reference > now.astimezone(tz).date():
            raise SeedError("O relógio atual é anterior à referência do seed.")
        return reference
    ids = [
        fixture_id(business_id, f"booking:{index}") for index in range(BOOKING_COUNT)
    ]
    ids += [fixture_id(business_id, f"block:{index}") for index in range(BLOCK_COUNT)]
    if session.scalar(
        select(Appointment.id)
        .where(Appointment.business_id == business_id, Appointment.id.in_(ids))
        .limit(1)
    ):
        raise SeedError(
            "Agendamentos do seed perderam seus metadados de referência; nada será substituído."
        )
    return now.astimezone(tz).date()


def existing[Model: (Category, Service, Professional, Client, Appointment)](
    session: Session, model: type[Model], business_id: UUID, key: str
) -> Model | None:
    return session.scalar(
        select(model).where(
            model.business_id == business_id, model.id == fixture_id(business_id, key)
        )
    )


def identify_new(session: Session, record: Any, business_id: UUID, key: str) -> None:
    # Services generate UUIDs. Only the newly inserted object receives its stable seed ID.
    record.id = fixture_id(business_id, key)
    session.flush()


def ensure_hours(
    session: Session, agenda: AppointmentService, business_id: UUID
) -> int:
    hours = agenda.get_hours(business_id=business_id)
    if hours:
        BusinessHoursUpdate(hours=hours)
        return 0
    validated = BusinessHoursUpdate(
        hours=[
            {"weekday": weekday, "opens_at": opens, "closes_at": closes}
            for weekday in range(6)
            for opens, closes in ((time(9), time(12)), (time(13), time(18)))
        ]
    )
    for index, hour in enumerate(validated.hours):
        session.add(
            BusinessHour(
                id=fixture_id(business_id, f"hours:{index}"),
                business_id=business_id,
                **hour.model_dump(),
            )
        )
    session.flush()
    return len(validated.hours)


def phone_for(session: Session, business_id: UUID, index: int) -> str:
    for attempt in range(100):
        # Non-routable synthetic area code; no real contact information.
        phone = f"000{attempt:04}{index:04}"
        if (
            session.scalar(
                select(Client.id).where(
                    Client.business_id == business_id, Client.phone == phone
                )
            )
            is None
        ):
            return phone
    raise SeedError("Não foi possível reservar um telefone fictício livre.")


def ensure_categories(
    session: Session, business_id: UUID, created: dict[str, int]
) -> dict[str, Category]:
    category_service = CategoryService(session)
    categories = {}
    for key, label in CATEGORIES.items():
        name = f"{MARKER} {label}"
        record = existing(session, Category, business_id, f"category:{key}")
        if record is None:
            record = category_service.repository.get_by_name(
                name, business_id=business_id
            )
        if record is None:
            record = category_service.create(
                CategoryCreate(name=name), business_id=business_id
            )
            identify_new(session, record, business_id, f"category:{key}")
            created["categories"] += 1
        categories[key] = record
    return categories


def create_catalog(
    session: Session,
    business_id: UUID,
    reference: date,
    tz: ZoneInfo,
    created: dict[str, int],
) -> tuple[list[Service], list[Professional], list[Client], int]:
    service_service = ServiceService(session)
    professional_service = ProfessionalService(session)
    client_service = ClientService(session)
    services, professionals, clients = [], [], []
    categories = ensure_categories(session, business_id, created)
    linked_existing_services = 0
    for index, (name, price, duration, category_key) in enumerate(SERVICES):
        key = f"service:{index}"
        record = existing(session, Service, business_id, key)
        if record is None:
            record = service_service.create(
                ServiceCreate(
                    business_id=business_id,
                    name=f"{MARKER} {name}",
                    price=Decimal(price),
                    duration_minutes=duration,
                    description=f"{MARKER} Serviço fictício.",
                    category_id=categories[category_key].id,
                )
            )
            identify_new(session, record, business_id, key)
            created["services"] += 1
        elif record.category_id is None:
            record = service_service.update(
                record.id,
                ServiceUpdate(category_id=categories[category_key].id),
                business_id=business_id,
            )
            linked_existing_services += 1
        services.append(record)
    for index in range(6):
        key = f"professional:{index}"
        record = existing(session, Professional, business_id, key)
        if record is None:
            record = professional_service.create(
                ProfessionalCreate(
                    business_id=business_id,
                    name=f"{MARKER} Profissional {index + 1:02}",
                    description=f"{MARKER} Profissional fictício.",
                    is_active=True,
                )
            )
            identify_new(session, record, business_id, key)
            created["professionals"] += 1
        professionals.append(record)
        desired = [
            services[(index * 2 + offset) % len(services)].id for offset in range(6)
        ]
        linked = set(
            session.scalars(
                select(professional_services.c.service_id).where(
                    professional_services.c.business_id == business_id,
                    professional_services.c.professional_id == record.id,
                )
            )
        )
        missing = [identifier for identifier in desired if identifier not in linked]
        professional_service._validate_services(missing, business_id=business_id)
        if missing:
            session.execute(
                insert(professional_services),
                [
                    {
                        "business_id": business_id,
                        "professional_id": record.id,
                        "service_id": identifier,
                    }
                    for identifier in missing
                ],
            )
            created["professional_services"] += len(missing)
    for index in range(80):
        key = f"client:{index}"
        record = existing(session, Client, business_id, key)
        if record is None:
            record = client_service.create(
                ClientCreate(
                    name=f"{MARKER} Cliente {index + 1:03}",
                    phone=phone_for(session, business_id, index),
                    email=f"cliente{index + 1:03}@example.com",
                    notes=metadata(reference, tz),
                ),
                business_id=business_id,
            )
            identify_new(session, record, business_id, key)
            record.created_at = datetime.combine(
                reference - timedelta(days=180), time(10), tz
            ).astimezone(UTC)
            session.flush()
            created["clients"] += 1
        clients.append(record)
    return services, professionals, clients, linked_existing_services


def find_slot(
    agenda: AppointmentService,
    business_id: UUID,
    service: Service,
    professional: Professional,
    preferred_day: date,
    direction: int,
    now: datetime,
    sequence: int,
    *,
    global_block: bool = False,
) -> tuple[datetime, datetime] | None:
    if not service.is_active or not professional.is_active:
        return None
    for shift in range(SEARCH_DAYS):
        day = preferred_day + timedelta(days=direction * shift)
        if direction > 0 and day > (now + BOOKING_WINDOW).astimezone(agenda.tz).date():
            break
        # Historical fixtures are booked using the Service's existing explicit clock argument.
        booking_now = min(
            now, datetime.combine(day - timedelta(days=1), time.min, agenda.tz)
        )
        slots = agenda.get_availability(
            business_id=business_id,
            service_id=service.id,
            professional_id=professional.id,
            day=day,
            now=booking_now,
        )
        if slots:
            offset = sequence % len(slots)
            for start in slots[offset:] + slots[:offset]:
                if global_block and agenda.repository.has_overlap(
                    business_id=business_id,
                    professional_id=None,
                    starts_at=start,
                    ends_at=start + timedelta(minutes=service.duration_minutes),
                ):
                    continue
                return start, booking_now
    return None


def create_agenda(
    session: Session,
    business_id: UUID,
    reference: date,
    tz: ZoneInfo,
    now: datetime,
    services: list[Service],
    professionals: list[Professional],
    clients: list[Client],
    created: dict[str, int],
) -> list[str]:
    agenda = AppointmentService(session, tz)
    unavailable = []
    # Blocks precede bookings, so availability already accounts for them.
    for kind, count in (("block", BLOCK_COUNT), ("booking", BOOKING_COUNT)):
        for index in range(count):
            key = f"{kind}:{index}"
            if existing(session, Appointment, business_id, key) is not None:
                continue
            past = index < count // 2
            direction = -1 if past else 1
            professional_index = index % len(professionals)
            professional = professionals[professional_index]
            service = services[
                (professional_index * 2 + (index // 6) % 6) % len(services)
            ]
            global_block = kind == "block" and index == BLOCK_COUNT - 1
            preferred = reference + timedelta(days=direction * (1 + index % 45))
            chosen = find_slot(
                agenda,
                business_id,
                service,
                professional,
                preferred,
                direction,
                now,
                index,
                global_block=global_block,
            )
            if chosen is None:
                unavailable.append(key)
                continue
            start, booking_now = chosen
            if kind == "block":
                record = agenda.create_block(
                    BlockCreateRequest(
                        professional_id=None if global_block else professional.id,
                        starts_at=start,
                        ends_at=start + timedelta(minutes=service.duration_minutes),
                        notes=f"{metadata(reference, tz)} {key}",
                    ),
                    business_id=business_id,
                )
            else:
                client = clients[index % len(clients)]
                record = agenda.book_panel(
                    OnlineBookingRequest(
                        service_id=service.id,
                        professional_id=professional.id,
                        starts_at=start,
                        customer_name=client.name,
                        customer_phone=client.phone,
                        customer_email=client.email,
                        notes=f"{metadata(reference, tz)} {key}",
                    ),
                    business_id=business_id,
                    now=booking_now,
                )
                status = AppointmentStatus.PENDING
                if index % 5 == 0:
                    status = AppointmentStatus.CANCELLED
                elif past or index % 5 in (1, 2):
                    status = AppointmentStatus.CONFIRMED
                if status != AppointmentStatus.PENDING:
                    record = agenda.update_status(
                        record.id,
                        AppointmentStatusUpdate(status=status),
                        business_id=business_id,
                    )
            identify_new(session, record, business_id, key)
            record.created_at = booking_now.astimezone(UTC)
            session.flush()
            created["blocks" if kind == "block" else "bookings"] += 1
    return unavailable


def guard_environment(app_env: str) -> None:
    if app_env not in ("development", "test"):
        raise SeedError("Seed operacional bloqueado fora de development/test.")


def seed_operational(
    engine: Engine,
    business_id: UUID,
    *,
    app_env: str,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> dict[str, Any]:
    guard_environment(app_env)
    if engine.dialect.name != "postgresql" and not (
        app_env == "test"
        and engine.dialect.name == "sqlite"
        and engine.url.database == ":memory:"
    ):
        raise SeedError(
            "A execução manual exige PostgreSQL; testes aceitam SQLite em memória."
        )
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise SeedError("O relógio precisa incluir fuso horário.")
    created = dict.fromkeys(
        (
            "categories",
            "professionals",
            "services",
            "professional_services",
            "clients",
            "business_hours",
            "bookings",
            "blocks",
        ),
        0,
    )
    # Services keep their commit/rollback behavior; only this outer transaction commits to the DB.
    with (
        engine.begin() as connection,
        Session(
            bind=connection,
            join_transaction_mode="rollback_only",
            expire_on_commit=False,
        ) as session,
    ):
        if (
            session.scalar(
                select(Business.id).where(Business.id == business_id).with_for_update()
            )
            is None
        ):
            raise SeedError("Empresa de testes não encontrada.")
        reference = find_reference(session, business_id, now, tz)
        created["business_hours"] = ensure_hours(
            session, AppointmentService(session, tz), business_id
        )
        services, professionals, clients, linked_existing_services = create_catalog(
            session, business_id, reference, tz, created
        )
        unavailable = create_agenda(
            session,
            business_id,
            reference,
            tz,
            now,
            services,
            professionals,
            clients,
            created,
        )
        session.flush()
    return {
        "business_id": str(business_id),
        "marker": MARKER,
        "reference_date": reference.isoformat(),
        "timezone": tz.key,
        "created": created,
        "linked_existing_services": linked_existing_services,
        "unavailable": unavailable,
        "note": "Registros existentes preservados. Itens sem disponibilidade não foram criados.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed operacional manual, sem lançamentos financeiros."
    )
    parser.add_argument(
        "--business-id",
        type=UUID,
        required=True,
        help="UUID da empresa de testes existente.",
    )
    args = parser.parse_args(argv)
    from app.core.config import settings

    try:
        guard_environment(settings.APP_ENV)
        from app.db.session import engine

        result = seed_operational(
            engine,
            args.business_id,
            app_env=settings.APP_ENV,
            tz=ZoneInfo(settings.BUSINESS_TIMEZONE),
        )
    except SeedError as exc:
        parser.exit(2, f"Seed recusado: {exc}\n")
    except (
        AppointmentError,
        BusinessError,
        CategoryError,
        ClientError,
        ProfessionalError,
        ServiceError,
    ):
        parser.exit(
            2,
            "Cadastro ou agenda recusaram a operação. A execução foi revertida; confira os dados operacionais existentes.\n",
        )
    except SQLAlchemyError:
        parser.exit(
            1,
            "Falha de banco. A execução foi revertida; confira conexão, migrations e permissões.\n",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
