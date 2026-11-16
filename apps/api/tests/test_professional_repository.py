from collections.abc import Iterator
from decimal import Decimal
from sqlite3 import Connection
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry

from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.models import Professional
from app.modules.professionals.repository import ProfessionalRepository
from app.modules.professionals.schemas import (
    ProfessionalCreate,
    ProfessionalResponse,
    ProfessionalServicesUpdate,
    ProfessionalUpdate,
)
from app.modules.services.associations import professional_services
from app.modules.services.models import Service


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        connection: Connection, record: ConnectionPoolEntry
    ) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        # Application databases use migrations; these tables exist only in memory.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine, autoflush=False) as session:
            yield session
    finally:
        engine.dispose()


@pytest.fixture
def businesses(session: Session) -> tuple[Business, Business]:
    category = BusinessCategory(name="Beauty")
    session.add(category)
    session.flush()
    first = Business(
        name="First",
        category_id=category.id,
        whatsapp="85999999999",
        service_mode=ServiceMode.HIBRIDO,
    )
    second = Business(
        name="Second",
        category_id=category.id,
        whatsapp="85999999999",
        service_mode=ServiceMode.HIBRIDO,
    )
    session.add_all([first, second])
    session.flush()
    return first, second


@pytest.fixture
def services(
    session: Session, businesses: tuple[Business, Business]
) -> tuple[Service, Service, Service]:
    services = [
        Service(
            name=str(index),
            business_id=business.id,
            price=Decimal("25.50"),
            duration_minutes=30,
        )
        for index, business in enumerate((businesses[0], businesses[0], businesses[1]))
    ]
    session.add_all(services)
    session.flush()
    return services[0], services[1], services[2]


def create_professional(
    repository: ProfessionalRepository,
    business_id: UUID,
    service_ids: list[UUID] | None = None,
    name: str = "Professional",
) -> Professional:
    return repository.create(
        ProfessionalCreate(
            business_id=business_id,
            name=name,
            phone="85999999999",
            description="Original",
            service_ids=service_ids or [],
        )
    )


@pytest.mark.parametrize("with_services", [False, True])
def test_create_persists_professional_and_association_business_id(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
    with_services: bool,
) -> None:
    repository = ProfessionalRepository(session)
    service_ids = [services[0].id, services[1].id] if with_services else []
    professional = create_professional(repository, businesses[0].id, service_ids)
    assert professional.id.version == 4
    assert professional.is_active is True
    assert {service.id for service in professional.services} == set(service_ids)
    links = session.execute(select(professional_services)).all()
    assert len(links) == len(service_ids)
    assert all(
        link.business_id == businesses[0].id and link.professional_id == professional.id
        for link in links
    )


def test_get_and_list_are_scoped_and_paginated(
    session: Session,
    businesses: tuple[Business, Business],
) -> None:
    repository = ProfessionalRepository(session)
    professionals = [
        create_professional(repository, businesses[0].id, name=str(index))
        for index in range(3)
    ]
    other_professional = create_professional(repository, businesses[1].id)
    expected = sorted(professionals, key=lambda professional: professional.id)
    assert (
        repository.get_by_id(professionals[0].id, business_id=businesses[0].id)
        is professionals[0]
    )
    assert (
        repository.get_by_id(professionals[0].id, business_id=businesses[1].id) is None
    )
    assert repository.get_by_id(uuid4(), business_id=businesses[0].id) is None
    assert repository.list(business_id=businesses[0].id) == expected
    assert (
        repository.list(business_id=businesses[0].id, offset=1, limit=1)
        == expected[1:2]
    )
    assert repository.list(business_id=businesses[0].id, offset=3) == []
    assert repository.list(business_id=businesses[1].id) == [other_professional]
    assert repository.list(business_id=uuid4()) == []


@pytest.mark.parametrize("is_active", [None, True, False])
def test_status_filter_is_scoped_applied_before_pagination_and_loads_services(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
    is_active: bool | None,
) -> None:
    repository = ProfessionalRepository(session)
    business_id = businesses[0].id
    service_id = services[0].id
    professionals = sorted(
        [create_professional(repository, business_id, [service_id]) for _ in range(4)],
        key=lambda professional: professional.id,
    )
    for index, professional in enumerate(professionals):
        repository.update(professional, ProfessionalUpdate(is_active=index % 2 == 0))
    for status in (True, False):
        other_professional = create_professional(
            repository, businesses[1].id, [services[2].id]
        )
        repository.update(other_professional, ProfessionalUpdate(is_active=status))
    expected_ids = [
        professional.id
        for professional in professionals
        if is_active is None or professional.is_active is is_active
    ]
    session.expunge_all()

    results = repository.list(business_id=business_id, is_active=is_active)
    assert [professional.id for professional in results] == expected_ids
    page = repository.list(
        business_id=business_id, is_active=is_active, offset=1, limit=1
    )
    assert [professional.id for professional in page] == expected_ids[1:2]
    assert (
        repository.list(
            business_id=business_id, is_active=is_active, offset=len(expected_ids)
        )
        == []
    )

    session.close()
    responses = [
        ProfessionalResponse.model_validate(professional) for professional in results
    ]
    assert all(response.business_id == business_id for response in responses)
    assert all(
        [service.id for service in response.services] == [service_id]
        for response in responses
    )


def test_partial_update_preserves_links_and_supports_deactivation(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
) -> None:
    repository = ProfessionalRepository(session)
    professional = create_professional(repository, businesses[0].id, [services[0].id])
    assert (
        repository.update(professional, ProfessionalUpdate(name="Updated"))
        is professional
    )
    assert professional.phone == "85999999999"
    assert professional.description == "Original"
    repository.update(
        professional, ProfessionalUpdate(phone=None, description=None, is_active=False)
    )
    session.refresh(professional)
    assert professional.name == "Updated"
    assert professional.phone is None
    assert professional.description is None
    assert professional.is_active is False
    assert professional.services == [services[0]]
    assert repository.update(professional, ProfessionalUpdate()) is professional


def test_replace_services_replaces_clears_and_refreshes_loaded_collection(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
) -> None:
    repository = ProfessionalRepository(session)
    first = create_professional(repository, businesses[0].id, [services[0].id])
    second = create_professional(repository, businesses[0].id, [services[0].id])
    ids = [services[0].id, services[1].id]
    assert (
        repository.replace_services(first, ProfessionalServicesUpdate(service_ids=ids))
        is first
    )
    assert {service.id for service in first.services} == set(ids)
    repository.replace_services(
        first, ProfessionalServicesUpdate(service_ids=[services[1].id])
    )
    assert first.services == [services[1]]
    # Repeating a PUT must not create duplicate associations.
    repository.replace_services(
        first, ProfessionalServicesUpdate(service_ids=[services[1].id])
    )
    assert len(first.services) == 1
    repository.replace_services(first, ProfessionalServicesUpdate(service_ids=[]))
    assert first.services == []
    assert second.services == [services[0]]
    assert session.get(Service, services[0].id) is services[0]
    assert session.get(Service, services[1].id) is services[1]


@pytest.mark.parametrize("invalid_link", ["missing", "other_business", "duplicate"])
@pytest.mark.parametrize("operation", ["create", "replace"])
def test_database_rejects_invalid_links_and_caller_can_roll_back(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
    invalid_link: str,
    operation: str,
) -> None:
    repository = ProfessionalRepository(session)
    professional = create_professional(repository, businesses[0].id, [services[0].id])
    professional_id = professional.id
    business_id = businesses[0].id
    valid_service_id = services[0].id
    invalid_ids = {
        "missing": [uuid4()],
        "other_business": [services[2].id],
        "duplicate": [services[1].id, services[1].id],
    }[invalid_link]
    session.commit()
    session.commit = Mock(wraps=session.commit)
    session.rollback = Mock(wraps=session.rollback)
    # Bypass schema validation only to exercise database constraints as a second defense.
    with pytest.raises(IntegrityError):
        if operation == "create":
            data = ProfessionalCreate(business_id=business_id, name="Invalid")
            data.service_ids.extend(invalid_ids)
            repository.create(data)
        else:
            data = ProfessionalServicesUpdate(service_ids=[])
            data.service_ids.extend(invalid_ids)
            repository.replace_services(professional, data)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.rollback()
    restored = repository.get_by_id(professional_id, business_id=business_id)
    assert [service.id for service in restored.services] == [valid_service_id]
    assert len(repository.list(business_id=business_id)) == 1


def test_deactivation_preserves_professional_links_and_services(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
) -> None:
    repository = ProfessionalRepository(session)
    professional = create_professional(repository, businesses[0].id, [services[0].id])
    professional_id = professional.id
    assert repository.get_by_id(professional_id, business_id=businesses[1].id) is None
    assert (
        repository.get_by_id(professional_id, business_id=businesses[0].id)
        is professional
    )
    repository.update(professional, ProfessionalUpdate(is_active=False))
    assert (
        repository.get_by_id(professional_id, business_id=businesses[0].id)
        is professional
    )
    assert professional.is_active is False
    assert professional.services == [services[0]]
    link = session.execute(select(professional_services)).one()
    assert link.professional_id == professional_id
    assert link.service_id == services[0].id
    assert link.business_id == businesses[0].id
    assert session.get(Service, services[0].id) is services[0]


@pytest.mark.parametrize("operation", ["get", "list"])
def test_queries_load_services_for_serialization_after_session_close(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
    operation: str,
) -> None:
    repository = ProfessionalRepository(session)
    professional = create_professional(repository, businesses[0].id, [services[0].id])
    professional_id = professional.id
    business_id = businesses[0].id
    service_id = services[0].id
    session.expunge_all()
    result = (
        repository.get_by_id(professional_id, business_id=business_id)
        if operation == "get"
        else repository.list(business_id=business_id)[0]
    )
    session.close()
    response = ProfessionalResponse.model_validate(result)
    assert response.id == professional_id
    assert response.services[0].id == service_id


def test_repository_leaves_transactions_to_caller(
    session: Session,
    businesses: tuple[Business, Business],
    services: tuple[Service, Service, Service],
) -> None:
    session.commit()
    business_id = businesses[0].id
    service_id = services[0].id
    session.commit = Mock(wraps=session.commit)
    session.rollback = Mock(wraps=session.rollback)
    repository = ProfessionalRepository(session)
    professional = create_professional(repository, business_id)
    repository.update(professional, ProfessionalUpdate(name="Updated"))
    repository.replace_services(
        professional, ProfessionalServicesUpdate(service_ids=[service_id])
    )
    repository.update(professional, ProfessionalUpdate(is_active=False))
    remaining_professional = create_professional(repository, business_id, [service_id])
    remaining_id = remaining_professional.id
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.rollback()
    assert repository.get_by_id(remaining_id, business_id=business_id) is None
    assert session.execute(select(professional_services)).all() == []
