from collections.abc import Iterator
from decimal import Decimal
from sqlite3 import Connection
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry

from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.repository import BusinessRepository
from app.modules.businesses.schemas import BusinessCreate, BusinessUpdate
from app.modules.professionals.models import Professional
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
        # Isolated ORM tests; application databases use Alembic migrations.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def create_business(session: Session, name: str = "Studio") -> Business:
    category = BusinessCategory(name=f"Category for {name}")
    session.add(category)
    session.flush()
    business = Business(
        name=name,
        category_id=category.id,
        whatsapp="85999999999",
        service_mode=ServiceMode.HIBRIDO,
    )
    session.add(business)
    session.flush()
    return business


def test_uuid_generation_and_relationships(session: Session) -> None:
    business = create_business(session)
    professional = Professional(name="Professional", business_id=business.id)
    service = Service(
        name="Service",
        business_id=business.id,
        price=Decimal("25.00"),
        duration_minutes=30,
    )
    session.add_all([professional, service])
    session.flush()
    session.execute(
        professional_services.insert().values(
            professional_id=professional.id,
            service_id=service.id,
            business_id=business.id,
        )
    )
    session.commit()

    identifiers = (business.id, professional.id, service.id)
    assert len(set(identifiers)) == 3
    assert all(
        isinstance(identifier, UUID) and identifier.version == 4
        for identifier in identifiers
    )
    assert isinstance(business.category_id, int)
    assert isinstance(business.category.id, int)
    assert professional.business is business
    assert service.business is business
    assert professional.services == [service]
    assert service.professionals == [professional]
    association = session.execute(select(professional_services)).one()
    assert association.professional_id == professional.id
    assert association.service_id == service.id
    assert association.business_id == business.id


@pytest.mark.parametrize("association_business", ["professional", "service"])
def test_association_rejects_different_businesses(
    session: Session, association_business: str
) -> None:
    first_business = create_business(session, "First")
    second_business = create_business(session, "Second")
    professional = Professional(name="Professional", business_id=first_business.id)
    service = Service(
        name="Service",
        business_id=second_business.id,
        price=Decimal("25.00"),
        duration_minutes=30,
    )
    session.add_all([professional, service])
    session.flush()
    association_business_id = (
        first_business.id
        if association_business == "professional"
        else second_business.id
    )
    with pytest.raises(IntegrityError):
        session.execute(
            professional_services.insert().values(
                professional_id=professional.id,
                service_id=service.id,
                business_id=association_business_id,
            )
        )
    session.rollback()


@pytest.mark.parametrize("model", [Professional, Service])
def test_business_foreign_key_rejects_unknown_uuid(
    session: Session, model: type[Professional] | type[Service]
) -> None:
    values = {"name": "Orphan", "business_id": uuid4()}
    if model is Service:
        values.update(price=Decimal("25.00"), duration_minutes=30)
    session.add(model(**values))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_repository_crud_with_uuid(session: Session) -> None:
    category = BusinessCategory(name="Beauty")
    session.add(category)
    session.flush()
    repository = BusinessRepository(session)
    business = repository.create(
        BusinessCreate(
            name="Studio",
            category_id=category.id,
            whatsapp="85999999999",
            service_mode="PRESENCIAL",
        )
    )
    business_id = business.id
    assert business_id.version == 4
    assert repository.get_by_id(business_id) is business
    assert repository.get_by_id(uuid4()) is None
    assert repository.list() == [business]
    assert repository.update(business, BusinessUpdate(name="Updated")).name == "Updated"
    assert repository.delete(business_id) is True
    assert repository.get_by_id(business_id) is None
    assert repository.delete(business_id) is False
