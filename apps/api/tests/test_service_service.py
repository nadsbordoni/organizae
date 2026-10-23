from collections.abc import Iterator
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.repository import BusinessRepository
from app.modules.professionals.models import Professional  # noqa: F401
from app.modules.services.exceptions import (
    InvalidServicePaginationError,
    ServiceConflictError,
    ServiceNotFoundError,
)
from app.modules.services.models import Service
from app.modules.services.repository import ServiceRepository
from app.modules.services.schemas import ServiceCreate, ServiceResponse, ServiceUpdate
from app.modules.services.service import ServiceService

business_id = uuid4()
service_id = uuid4()


@pytest.fixture
def service() -> ServiceService:
    service = ServiceService(Mock(spec=Session))
    service.repository = Mock(spec=ServiceRepository)
    service.business_repository = Mock(spec=BusinessRepository)
    return service


@pytest.fixture
def service_data() -> ServiceCreate:
    return ServiceCreate(
        business_id=business_id, name="Haircut", price="25.50", duration_minutes=30
    )


def test_create_validates_business_and_commits(
    service: ServiceService, service_data: ServiceCreate
) -> None:
    result = service.create(service_data)
    service.business_repository.get_by_id.assert_called_once_with(business_id)
    service.repository.create.assert_called_once_with(service_data)
    assert result is service.repository.create.return_value
    service.session.commit.assert_called_once_with()
    service.session.refresh.assert_called_once_with(result)
    service.session.rollback.assert_not_called()


def test_create_rejects_missing_business(
    service: ServiceService, service_data: ServiceCreate
) -> None:
    service.business_repository.get_by_id.return_value = None
    with pytest.raises(BusinessNotFoundError):
        service.create(service_data)
    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_get_is_scoped_and_does_not_commit(service: ServiceService) -> None:
    assert (
        service.get_by_id(service_id, business_id=business_id)
        is service.repository.get_by_id.return_value
    )
    service.repository.get_by_id.assert_called_once_with(
        service_id, business_id=business_id
    )
    service.session.commit.assert_not_called()


def test_get_missing_service(service: ServiceService) -> None:
    service.repository.get_by_id.return_value = None
    with pytest.raises(ServiceNotFoundError):
        service.get_by_id(service_id, business_id=business_id)


def test_list_is_scoped_and_paginated(service: ServiceService) -> None:
    service.repository.list.return_value = []
    assert service.list(business_id=business_id, offset=10, limit=5) == []
    service.repository.list.assert_called_once_with(
        business_id=business_id, offset=10, limit=5
    )
    service.session.commit.assert_not_called()


@pytest.mark.parametrize("offset, limit", [(-1, 10), (0, 0), (0, -1)])
def test_invalid_pagination(service: ServiceService, offset: int, limit: int) -> None:
    with pytest.raises(InvalidServicePaginationError):
        service.list(business_id=business_id, offset=offset, limit=limit)
    service.repository.list.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Updated"},
        {"description": None},
        {"is_active": False},
        {"price": "0"},
        {},
    ],
)
def test_update_reuses_loaded_entity(
    service: ServiceService, payload: dict[str, object]
) -> None:
    data = ServiceUpdate(**payload)
    result = service.update(service_id, data, business_id=business_id)
    service.repository.get_by_id.assert_called_once_with(
        service_id, business_id=business_id
    )
    service.repository.update.assert_called_once_with(
        service.repository.get_by_id.return_value, data
    )
    assert result is service.repository.update.return_value
    service.session.commit.assert_called_once_with()
    service.session.refresh.assert_called_once_with(result)
    service.session.rollback.assert_not_called()


def test_update_missing_service_rolls_back(service: ServiceService) -> None:
    service.repository.get_by_id.return_value = None
    with pytest.raises(ServiceNotFoundError):
        service.update(service_id, ServiceUpdate(), business_id=business_id)
    service.repository.update.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_delete_is_scoped_and_commits(service: ServiceService) -> None:
    assert service.delete(service_id, business_id=business_id) is None
    service.repository.delete.assert_called_once_with(
        service_id, business_id=business_id
    )
    service.session.commit.assert_called_once_with()
    service.session.rollback.assert_not_called()


def test_delete_missing_service_rolls_back(service: ServiceService) -> None:
    service.repository.delete.return_value = False
    with pytest.raises(ServiceNotFoundError):
        service.delete(service_id, business_id=business_id)
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("failure_stage", ["flush", "commit"])
def test_integrity_errors_roll_back_and_become_conflicts(
    service: ServiceService,
    service_data: ServiceCreate,
    operation: str,
    failure_stage: str,
) -> None:
    error = IntegrityError("sensitive SQL", {}, Exception("internal details"))
    target = (
        service.session.commit
        if failure_stage == "commit"
        else getattr(service.repository, operation)
    )
    target.side_effect = error
    with pytest.raises(ServiceConflictError) as caught:
        if operation == "create":
            service.create(service_data)
        elif operation == "update":
            service.update(service_id, ServiceUpdate(), business_id=business_id)
        else:
            service.delete(service_id, business_id=business_id)
    assert "sensitive SQL" not in str(caught.value)
    assert "internal details" not in str(caught.value)
    service.session.rollback.assert_called_once_with()
    if failure_stage == "flush":
        service.session.commit.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["query", "flush", "commit", "refresh"])
@pytest.mark.parametrize("error_type", [OperationalError, RuntimeError])
def test_errors_are_rolled_back_and_propagated(
    service: ServiceService,
    service_data: ServiceCreate,
    failure_stage: str,
    error_type: type[Exception],
) -> None:
    error = (
        OperationalError("statement", {}, Exception("failure"))
        if error_type is OperationalError
        else RuntimeError("failure")
    )
    target = {
        "query": service.business_repository.get_by_id,
        "flush": service.repository.create,
        "commit": service.session.commit,
        "refresh": service.session.refresh,
    }[failure_stage]
    target.side_effect = error
    with pytest.raises(error_type) as caught:
        service.create(service_data)
    assert caught.value is error
    service.session.rollback.assert_called_once_with()
    if failure_stage in ("query", "flush"):
        service.session.commit.assert_not_called()


@pytest.fixture
def database_session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    try:
        # Isolated ORM tests; application databases use migrations.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine, autoflush=False, expire_on_commit=True) as session:
            session.add(BusinessCategory(id=1, name="Beauty"))
            session.flush()
            session.add(
                Business(
                    id=business_id,
                    name="Studio",
                    category_id=1,
                    whatsapp="85999999999",
                    service_mode=ServiceMode.HIBRIDO,
                )
            )
            session.commit()
            yield session
    finally:
        engine.dispose()


@pytest.mark.parametrize("update", [False, True])
def test_returned_fields_survive_commit_and_session_close(
    database_session: Session, service_data: ServiceCreate, update: bool
) -> None:
    service = ServiceService(database_session)
    entity = service.create(service_data)
    if update:
        entity = service.update(
            entity.id,
            ServiceUpdate(name="Updated", description=None, is_active=False),
            business_id=business_id,
        )
    database_session.close()
    response = ServiceResponse.model_validate(entity)
    assert response.id.version == 4
    assert response.business_id == business_id
    assert response.name == ("Updated" if update else "Haircut")
    assert response.is_active is (not update)


def test_real_crud_is_scoped_to_business(
    database_session: Session, service_data: ServiceCreate
) -> None:
    service = ServiceService(database_session)
    entity = service.create(service_data)
    entity_id = entity.id
    other_business_id = uuid4()
    assert service.list(business_id=business_id) == [entity]
    assert service.list(business_id=other_business_id) == []
    assert service.get_by_id(entity_id, business_id=business_id) is entity
    with pytest.raises(ServiceNotFoundError):
        service.get_by_id(entity_id, business_id=other_business_id)
    with pytest.raises(ServiceNotFoundError):
        service.update(
            entity_id, ServiceUpdate(name="Wrong"), business_id=other_business_id
        )
    with pytest.raises(ServiceNotFoundError):
        service.delete(entity_id, business_id=other_business_id)
    assert service.get_by_id(entity_id, business_id=business_id).name == "Haircut"
    service.delete(entity_id, business_id=business_id)
    assert service.list(business_id=business_id) == []


def test_real_rollback_removes_flushed_write(
    database_session: Session, service_data: ServiceCreate
) -> None:
    service = ServiceService(database_session)
    original_create = service.repository.create

    def fail_after_flush(data: ServiceCreate) -> Service:
        original_create(data)
        raise RuntimeError("after flush")

    service.repository.create = Mock(side_effect=fail_after_flush)
    with pytest.raises(RuntimeError, match="after flush"):
        service.create(service_data)
    assert database_session.scalars(select(Service)).all() == []
    assert service.business_repository.get_by_id(business_id) is not None
