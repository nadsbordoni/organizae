from collections.abc import Iterator
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
from app.modules.services.associations import professional_services
from app.modules.services.models import Service
from app.modules.services.repository import ServiceRepository
from app.modules.services.schemas import ServiceCreate, ServiceUpdate


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        connection: Connection, record: ConnectionPoolEntry
    ) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        # Only the isolated test database uses tables created from metadata.
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
    businesses = tuple(
        Business(
            name=name,
            category_id=category.id,
            whatsapp="85999999999",
            service_mode=ServiceMode.PRESENCIAL,
        )
        for name in ("First", "Second")
    )
    session.add_all(businesses)
    session.flush()
    return businesses


def create_service(
    repository: ServiceRepository, business_id: UUID, name: str = "Haircut"
) -> Service:
    return repository.create(
        ServiceCreate(
            business_id=business_id,
            name=name,
            price="25.50",
            duration_minutes=30,
            description="Original",
        )
    )


def test_create_flushes_and_returns_uuid(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    repository = ServiceRepository(session)
    service = create_service(repository, businesses[0].id)

    assert service.id.version == 4
    assert service.business_id == businesses[0].id
    assert service.is_active is True
    assert session.get(Service, service.id) is service


def test_get_by_id_is_scoped_even_for_a_loaded_entity(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    repository = ServiceRepository(session)
    service = create_service(repository, businesses[0].id)

    assert repository.get_by_id(service.id, business_id=businesses[0].id) is service
    assert repository.get_by_id(service.id, business_id=businesses[1].id) is None
    assert repository.get_by_id(uuid4(), business_id=businesses[0].id) is None


def test_list_filters_before_ordering_and_pagination(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    repository = ServiceRepository(session)
    services = [
        create_service(repository, businesses[0].id, str(index)) for index in range(3)
    ]
    other_service = create_service(repository, businesses[1].id)
    services[0].is_active = False
    session.flush()
    expected = sorted(services, key=lambda service: service.id)

    assert repository.list(business_id=businesses[0].id) == expected
    assert (
        repository.list(business_id=businesses[0].id, offset=1, limit=1)
        == expected[1:2]
    )
    assert repository.list(business_id=businesses[0].id, offset=3) == []
    assert repository.list(business_id=businesses[1].id) == [other_service]
    assert repository.list(business_id=uuid4()) == []


def test_partial_update_preserves_omitted_fields(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    repository = ServiceRepository(session)
    service = create_service(repository, businesses[0].id)
    original_price = service.price
    session.get = Mock(wraps=session.get)

    assert repository.update(service, ServiceUpdate(name="Updated")) is service
    session.get.assert_not_called()
    session.refresh(service)
    assert service.name == "Updated"
    assert service.price == original_price
    assert service.description == "Original"
    assert service.duration_minutes == 30
    assert service.business_id == businesses[0].id

    repository.update(
        service, ServiceUpdate(description=None, price="0", is_active=False)
    )
    session.refresh(service)
    assert service.description is None
    assert service.price == 0
    assert service.is_active is False
    assert repository.update(service, ServiceUpdate()) is service


def test_delete_is_scoped_and_handles_missing_service(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    repository = ServiceRepository(session)
    service = create_service(repository, businesses[0].id)
    service_id = service.id

    assert repository.delete(service_id, business_id=businesses[1].id) is False
    assert repository.get_by_id(service_id, business_id=businesses[0].id) is service
    assert repository.delete(service_id, business_id=businesses[0].id) is True
    assert repository.get_by_id(service_id, business_id=businesses[0].id) is None
    assert repository.delete(service_id, business_id=businesses[0].id) is False


def test_delete_removes_association_and_preserves_professional(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    repository = ServiceRepository(session)
    service = create_service(repository, businesses[0].id)
    professional = Professional(name="Professional", business_id=businesses[0].id)
    session.add(professional)
    session.flush()
    session.execute(
        professional_services.insert().values(
            professional_id=professional.id,
            service_id=service.id,
            business_id=businesses[0].id,
        )
    )

    assert repository.delete(service.id, business_id=businesses[0].id) is True
    assert session.execute(select(professional_services)).all() == []
    assert session.get(Professional, professional.id) is professional


def test_repository_leaves_transaction_control_to_caller(
    session: Session, businesses: tuple[Business, Business]
) -> None:
    session.commit()
    business_id = businesses[0].id
    session.commit = Mock(wraps=session.commit)
    session.rollback = Mock(wraps=session.rollback)
    repository = ServiceRepository(session)
    service = create_service(repository, business_id)
    service_id = service.id
    repository.update(service, ServiceUpdate(name="Updated"))
    repository.delete(service_id, business_id=business_id)
    remaining_service = create_service(repository, business_id)
    remaining_id = remaining_service.id

    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.rollback()
    assert repository.get_by_id(remaining_id, business_id=business_id) is None


def test_integrity_error_propagates_without_transaction_control(
    session: Session,
) -> None:
    session.commit = Mock(wraps=session.commit)
    session.rollback = Mock(wraps=session.rollback)

    with pytest.raises(IntegrityError):
        create_service(ServiceRepository(session), uuid4())

    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.rollback()
