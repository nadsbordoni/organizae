from collections.abc import Iterator
from decimal import Decimal
from sqlite3 import Connection
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry

from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.repository import BusinessRepository
from app.modules.professionals.exceptions import (
    InvalidProfessionalPaginationError,
    InvalidProfessionalServicesError,
    ProfessionalConflictError,
    ProfessionalNotFoundError,
)
from app.modules.professionals.repository import ProfessionalRepository
from app.modules.professionals.schemas import (
    ProfessionalCreate,
    ProfessionalResponse,
    ProfessionalServicesUpdate,
    ProfessionalUpdate,
)
from app.modules.professionals.service import ProfessionalService
from app.modules.services.models import Service
from app.modules.services.repository import ServiceRepository

business_id = uuid4()
other_business_id = uuid4()
first_service_id, second_service_id, other_service_id = uuid4(), uuid4(), uuid4()
professional_id = uuid4()


@pytest.fixture
def data() -> ProfessionalCreate:
    return ProfessionalCreate(
        business_id=business_id, name="Professional", service_ids=[first_service_id]
    )


@pytest.fixture
def service() -> ProfessionalService:
    service = ProfessionalService(Mock(spec=Session))
    service.repository = Mock(spec=ProfessionalRepository)
    service.business_repository = Mock(spec=BusinessRepository)
    service.service_repository = Mock(spec=ServiceRepository)
    return service


def test_create_validates_business_and_services_before_persistence(
    service: ProfessionalService, data: ProfessionalCreate
) -> None:
    result = service.create(data)
    service.business_repository.get_by_id.assert_called_once_with(business_id)
    service.service_repository.get_by_id.assert_called_once_with(
        first_service_id, business_id=business_id
    )
    service.repository.create.assert_called_once_with(data)
    assert result is service.repository.create.return_value
    service.session.commit.assert_called_once_with()
    service.session.refresh.assert_any_call(result, attribute_names=["services"])
    service.session.rollback.assert_not_called()


def test_create_rejects_missing_business(
    service: ProfessionalService, data: ProfessionalCreate
) -> None:
    service.business_repository.get_by_id.return_value = None
    with pytest.raises(BusinessNotFoundError):
        service.create(data)
    service.repository.create.assert_not_called()
    service.service_repository.get_by_id.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize("operation", ["create", "replace_services"])
def test_duplicate_ids_are_rejected_before_any_write(
    service: ProfessionalService, data: ProfessionalCreate, operation: str
) -> None:
    data.service_ids.append(first_service_id)
    replacement = ProfessionalServicesUpdate(service_ids=[])
    replacement.service_ids.extend(data.service_ids)
    with pytest.raises(InvalidProfessionalServicesError, match="duplicates"):
        if operation == "create":
            service.create(data)
        else:
            service.replace_services(
                professional_id, replacement, business_id=business_id
            )
    service.repository.create.assert_not_called()
    service.repository.replace_services.assert_not_called()
    service.service_repository.get_by_id.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize("offset, limit", [(-1, 10), (0, 0), (0, 101)])
def test_pagination_validation(
    service: ProfessionalService, offset: int, limit: int
) -> None:
    with pytest.raises(InvalidProfessionalPaginationError):
        service.list(business_id=business_id, offset=offset, limit=limit)
    service.repository.list.assert_not_called()


@pytest.mark.parametrize("is_active", [None, True, False])
def test_list_forwards_status_filter_without_writing(
    service: ProfessionalService, is_active: bool | None
) -> None:
    service.repository.list.return_value = []
    assert (
        service.list(business_id=business_id, is_active=is_active, offset=10, limit=5)
        == []
    )
    service.repository.list.assert_called_once_with(
        business_id=business_id, is_active=is_active, offset=10, limit=5
    )
    service.session.commit.assert_not_called()
    service.session.rollback.assert_not_called()


def test_update_reuses_scoped_entity(service: ProfessionalService) -> None:
    data = ProfessionalUpdate(phone=None)
    result = service.update(professional_id, data, business_id=business_id)
    service.repository.get_by_id.assert_called_once_with(
        professional_id, business_id=business_id
    )
    service.repository.update.assert_called_once_with(
        service.repository.get_by_id.return_value, data
    )
    assert result is service.repository.update.return_value


def test_delete_deactivates_instead_of_deleting(service: ProfessionalService) -> None:
    assert service.delete(professional_id, business_id=business_id) is None
    service.repository.get_by_id.assert_called_once_with(
        professional_id, business_id=business_id
    )
    service.repository.update.assert_called_once_with(
        service.repository.get_by_id.return_value, ProfessionalUpdate(is_active=False)
    )
    service.session.delete.assert_not_called()
    service.repository.replace_services.assert_not_called()
    service.session.commit.assert_called_once_with()


@pytest.mark.parametrize("operation", ["update", "replace_services", "delete"])
def test_missing_professional_does_not_write(
    service: ProfessionalService, operation: str
) -> None:
    service.repository.get_by_id.return_value = None
    with pytest.raises(ProfessionalNotFoundError):
        if operation == "update":
            service.update(
                professional_id, ProfessionalUpdate(), business_id=business_id
            )
        elif operation == "replace_services":
            service.replace_services(
                professional_id,
                ProfessionalServicesUpdate(service_ids=[]),
                business_id=business_id,
            )
        else:
            service.delete(professional_id, business_id=business_id)
    service.repository.update.assert_not_called()
    service.repository.replace_services.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize(
    "operation", ["create", "update", "replace_services", "delete"]
)
@pytest.mark.parametrize("stage", ["write", "commit"])
@pytest.mark.parametrize("error_type", [IntegrityError, OperationalError, RuntimeError])
def test_write_failures_roll_back_and_preserve_error_semantics(
    service: ProfessionalService,
    data: ProfessionalCreate,
    operation: str,
    stage: str,
    error_type: type[Exception],
) -> None:
    error = (
        error_type("sensitive SQL", {}, Exception("internal details"))
        if error_type is not RuntimeError
        else RuntimeError("failure")
    )
    target = (
        service.session.commit
        if stage == "commit"
        else getattr(
            service.repository, "update" if operation == "delete" else operation
        )
    )
    target.side_effect = error
    expected = ProfessionalConflictError if error_type is IntegrityError else error_type
    with pytest.raises(expected) as caught:
        if operation == "create":
            service.create(data)
        elif operation == "update":
            service.update(
                professional_id,
                ProfessionalUpdate(name="Updated"),
                business_id=business_id,
            )
        elif operation == "replace_services":
            service.replace_services(
                professional_id,
                ProfessionalServicesUpdate(service_ids=[second_service_id]),
                business_id=business_id,
            )
        else:
            service.delete(professional_id, business_id=business_id)
    if error_type is IntegrityError:
        assert "sensitive SQL" not in str(caught.value)
        assert "internal details" not in str(caught.value)
    else:
        assert caught.value is error
    service.session.rollback.assert_called_once_with()
    if stage == "write":
        service.session.commit.assert_not_called()


@pytest.mark.parametrize("refresh_services", [False, True])
def test_refresh_failure_rolls_back_current_transaction(
    service: ProfessionalService, data: ProfessionalCreate, refresh_services: bool
) -> None:
    error = OperationalError("statement", {}, Exception("connection failed"))
    service.session.refresh.side_effect = [None, error] if refresh_services else error
    with pytest.raises(OperationalError) as caught:
        service.create(data)
    assert caught.value is error
    service.session.commit.assert_called_once_with()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize(
    "operation, lookup",
    [
        ("create", "business"),
        ("create", "services"),
        ("update", "professional"),
        ("replace_services", "professional"),
        ("replace_services", "services"),
        ("delete", "professional"),
    ],
)
def test_lookup_failures_roll_back_without_writing(
    service: ProfessionalService, data: ProfessionalCreate, operation: str, lookup: str
) -> None:
    error = OperationalError("statement", {}, Exception("connection failed"))
    target = {
        "business": service.business_repository.get_by_id,
        "services": service.service_repository.get_by_id,
        "professional": service.repository.get_by_id,
    }[lookup]
    target.side_effect = error
    with pytest.raises(OperationalError) as caught:
        if operation == "create":
            service.create(data)
        elif operation == "update":
            service.update(
                professional_id, ProfessionalUpdate(), business_id=business_id
            )
        elif operation == "replace_services":
            service.replace_services(
                professional_id,
                ProfessionalServicesUpdate(service_ids=[first_service_id]),
                business_id=business_id,
            )
        else:
            service.delete(professional_id, business_id=business_id)
    assert caught.value is error
    service.repository.create.assert_not_called()
    service.repository.update.assert_not_called()
    service.repository.replace_services.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.fixture
def database_session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        connection: Connection, record: ConnectionPoolEntry
    ) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        # Only the isolated test database uses metadata to create tables.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine, autoflush=False, expire_on_commit=True) as session:
            session.add(BusinessCategory(id=1, name="Beauty"))
            session.flush()
            session.add_all(
                [
                    Business(
                        id=identifier,
                        name=str(index),
                        category_id=1,
                        whatsapp="85999999999",
                        service_mode=ServiceMode.HIBRIDO,
                    )
                    for index, identifier in enumerate((business_id, other_business_id))
                ]
            )
            session.flush()
            session.add_all(
                [
                    Service(
                        id=identifier,
                        business_id=owner,
                        name=str(index),
                        price=Decimal("25.50"),
                        duration_minutes=30,
                    )
                    for index, (identifier, owner) in enumerate(
                        (
                            (first_service_id, business_id),
                            (second_service_id, business_id),
                            (other_service_id, other_business_id),
                        )
                    )
                ]
            )
            session.commit()
            yield session
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["create", "replace_services"])
@pytest.mark.parametrize("invalid_id", [other_service_id, uuid4()])
def test_invalid_services_leave_existing_links_untouched(
    database_session: Session,
    data: ProfessionalCreate,
    operation: str,
    invalid_id: UUID,
) -> None:
    service = ProfessionalService(database_session)
    identifier = service.create(data).id
    # Include a valid service first to ensure partial validation never writes links.
    ids = [second_service_id, invalid_id]
    with pytest.raises(InvalidProfessionalServicesError):
        if operation == "create":
            service.create(data.model_copy(update={"service_ids": ids}))
        else:
            service.replace_services(
                identifier,
                ProfessionalServicesUpdate(service_ids=ids),
                business_id=business_id,
            )
    result = service.get_by_id(identifier, business_id=business_id)
    assert [item.id for item in result.services] == [first_service_id]
    assert len(service.list(business_id=business_id)) == 1


@pytest.mark.parametrize("operation", ["get", "update", "replace_services", "delete"])
def test_existing_other_business_cannot_access_professional(
    database_session: Session, data: ProfessionalCreate, operation: str
) -> None:
    service = ProfessionalService(database_session)
    identifier = service.create(data).id
    with pytest.raises(ProfessionalNotFoundError):
        if operation == "get":
            service.get_by_id(identifier, business_id=other_business_id)
        elif operation == "update":
            service.update(
                identifier,
                ProfessionalUpdate(name="Wrong"),
                business_id=other_business_id,
            )
        elif operation == "replace_services":
            service.replace_services(
                identifier,
                ProfessionalServicesUpdate(service_ids=[]),
                business_id=other_business_id,
            )
        else:
            service.delete(identifier, business_id=other_business_id)
    result = service.get_by_id(identifier, business_id=business_id)
    assert result.name == "Professional"
    assert result.is_active is True
    assert [item.id for item in result.services] == [first_service_id]
    assert service.list(business_id=other_business_id) == []


@pytest.mark.parametrize("operation", ["create", "update", "replace_services"])
def test_response_survives_commit_and_session_close(
    database_session: Session, data: ProfessionalCreate, operation: str
) -> None:
    service = ProfessionalService(database_session)
    result = service.create(data)
    if operation == "update":
        result = service.update(
            result.id, ProfessionalUpdate(phone=None), business_id=business_id
        )
    elif operation == "replace_services":
        result = service.replace_services(
            result.id,
            ProfessionalServicesUpdate(service_ids=[second_service_id]),
            business_id=business_id,
        )
    database_session.close()
    response = ProfessionalResponse.model_validate(result)
    assert response.id.version == 4
    expected = (
        second_service_id if operation == "replace_services" else first_service_id
    )
    assert response.services[0].id == expected


def test_complete_replacement_and_soft_delete_are_idempotent(
    database_session: Session, data: ProfessionalCreate
) -> None:
    service = ProfessionalService(database_session)
    identifier = service.create(data).id
    replacement = ProfessionalServicesUpdate(service_ids=[second_service_id])
    for _ in range(2):
        result = service.replace_services(
            identifier, replacement, business_id=business_id
        )
        assert [item.id for item in result.services] == [second_service_id]
    for _ in range(2):
        service.delete(identifier, business_id=business_id)
    result = service.get_by_id(identifier, business_id=business_id)
    assert result.is_active is False
    assert [item.id for item in result.services] == [second_service_id]
    assert service.list(business_id=business_id) == [result]
    assert (
        service.replace_services(
            identifier,
            ProfessionalServicesUpdate(service_ids=[]),
            business_id=business_id,
        ).services
        == []
    )


@pytest.mark.parametrize(
    "operation", ["create", "update", "replace_services", "delete"]
)
def test_rollback_restores_data_and_associations(
    database_session: Session, data: ProfessionalCreate, operation: str
) -> None:
    service = ProfessionalService(database_session)
    identifier = service.create(data).id
    method_name = "update" if operation == "delete" else operation
    original = getattr(service.repository, method_name)

    def fail_after_write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        raise RuntimeError("after write")

    setattr(service.repository, method_name, Mock(side_effect=fail_after_write))
    with pytest.raises(RuntimeError, match="after write"):
        if operation == "create":
            service.create(data)
        elif operation == "update":
            service.update(
                identifier, ProfessionalUpdate(name="Changed"), business_id=business_id
            )
        elif operation == "replace_services":
            service.replace_services(
                identifier,
                ProfessionalServicesUpdate(service_ids=[second_service_id]),
                business_id=business_id,
            )
        else:
            service.delete(identifier, business_id=business_id)
    restored = service.get_by_id(identifier, business_id=business_id)
    assert restored.name == "Professional"
    assert restored.is_active is True
    assert [item.id for item in restored.services] == [first_service_id]
    assert len(service.list(business_id=business_id)) == 1
