from collections.abc import Iterator
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business
from app.modules.businesses.repository import BusinessRepository
from app.modules.businesses.schemas import (
    BusinessCreate,
    BusinessResponse,
    BusinessUpdate,
)
from app.modules.businesses.service import (
    BusinessCategoryNotFoundError,
    BusinessConflictError,
    BusinessNotFoundError,
    BusinessService,
    InvalidBusinessPaginationError,
)
from app.modules.professionals.models import Professional  # noqa: F401
from app.modules.services.models import Service  # noqa: F401

business_id = UUID("8ccacb20-1d36-44a7-9d32-08ac5f6bf15e")


@pytest.fixture
def service() -> BusinessService:
    session = Mock(spec=Session)
    service = BusinessService(session)
    service.repository = Mock(spec=BusinessRepository)
    return service


@pytest.fixture
def business_data() -> BusinessCreate:
    return BusinessCreate(
        name="Studio", category_id=1, whatsapp="85999999999", service_mode="HIBRIDO"
    )


def test_create_validates_category_and_commits(
    service: BusinessService, business_data: BusinessCreate
) -> None:
    business = service.create(business_data)

    service.session.get.assert_called_once_with(BusinessCategory, 1)
    service.repository.create.assert_called_once_with(business_data)
    assert business is service.repository.create.return_value
    service.session.commit.assert_called_once_with()
    service.session.refresh.assert_called_once_with(business)
    service.session.rollback.assert_not_called()


def test_create_rejects_missing_category(
    service: BusinessService, business_data: BusinessCreate
) -> None:
    service.session.get.return_value = None

    with pytest.raises(BusinessCategoryNotFoundError):
        service.create(business_data)

    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_get_existing_business(service: BusinessService) -> None:
    assert service.get_by_id(business_id) is service.repository.get_by_id.return_value
    service.repository.get_by_id.assert_called_once_with(business_id)
    service.session.commit.assert_not_called()


def test_get_missing_business(service: BusinessService) -> None:
    service.repository.get_by_id.return_value = None
    with pytest.raises(BusinessNotFoundError):
        service.get_by_id(business_id)


def test_list_passes_pagination_without_committing(service: BusinessService) -> None:
    service.repository.list.return_value = []
    assert service.list(offset=10, limit=5) == []
    service.repository.list.assert_called_once_with(offset=10, limit=5)
    service.session.commit.assert_not_called()


@pytest.mark.parametrize("offset, limit", [(-1, 10), (0, 0), (0, -1)])
def test_list_rejects_invalid_pagination(
    service: BusinessService, offset: int, limit: int
) -> None:
    with pytest.raises(InvalidBusinessPaginationError):
        service.list(offset=offset, limit=limit)
    service.repository.list.assert_not_called()


@pytest.mark.parametrize("payload", [{"name": "Updated"}, {"description": None}, {}])
def test_update_preserves_partial_update_contract(
    service: BusinessService, payload: dict[str, str | None]
) -> None:
    business_data = BusinessUpdate(**payload)
    assert (
        service.update(business_id, business_data)
        is service.repository.update.return_value
    )
    service.repository.get_by_id.assert_called_once_with(business_id)
    service.repository.update.assert_called_once_with(
        service.repository.get_by_id.return_value, business_data
    )
    service.session.refresh.assert_called_once_with(
        service.repository.update.return_value
    )
    assert business_data.model_dump(exclude_unset=True) == payload
    service.session.get.assert_not_called()
    service.session.commit.assert_called_once_with()


def test_update_validates_new_category(service: BusinessService) -> None:
    service.update(business_id, BusinessUpdate(category_id=2))
    service.session.get.assert_called_once_with(BusinessCategory, 2)
    service.session.commit.assert_called_once_with()


def test_update_rejects_missing_category(service: BusinessService) -> None:
    service.session.get.return_value = None
    with pytest.raises(BusinessCategoryNotFoundError):
        service.update(business_id, BusinessUpdate(category_id=2))
    service.repository.update.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_update_missing_business(service: BusinessService) -> None:
    service.repository.get_by_id.return_value = None
    with pytest.raises(BusinessNotFoundError):
        service.update(business_id, BusinessUpdate(name="Updated"))
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()
    service.repository.update.assert_not_called()


def test_update_missing_business_takes_precedence_over_category(
    service: BusinessService,
) -> None:
    service.repository.get_by_id.return_value = None
    service.session.get.return_value = None
    with pytest.raises(BusinessNotFoundError):
        service.update(business_id, BusinessUpdate(category_id=2))
    service.session.get.assert_not_called()
    service.repository.update.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_delete_commits(service: BusinessService) -> None:
    assert service.delete(business_id) is None
    service.repository.delete.assert_called_once_with(business_id)
    service.session.commit.assert_called_once_with()


def test_delete_missing_business(service: BusinessService) -> None:
    service.repository.delete.return_value = False
    with pytest.raises(BusinessNotFoundError):
        service.delete(business_id)
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("failure_stage", ["flush", "commit"])
def test_integrity_failure_rolls_back_and_hides_database_details(
    service: BusinessService,
    business_data: BusinessCreate,
    operation: str,
    failure_stage: str,
) -> None:
    error = IntegrityError(
        "SQL with sensitive values", {}, Exception("internal detail")
    )
    if failure_stage == "commit":
        service.session.commit.side_effect = error
    else:
        getattr(service.repository, operation).side_effect = error

    with pytest.raises(BusinessConflictError) as caught:
        if operation == "create":
            service.create(business_data)
        elif operation == "update":
            service.update(business_id, BusinessUpdate(name="Updated"))
        else:
            service.delete(business_id)

    assert "sensitive" not in str(caught.value)
    assert "internal detail" not in str(caught.value)
    service.session.rollback.assert_called_once_with()
    if failure_stage == "flush":
        service.session.commit.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["query", "flush", "commit"])
def test_database_errors_are_rolled_back_and_propagated(
    service: BusinessService, business_data: BusinessCreate, failure_stage: str
) -> None:
    error = OperationalError("statement", {}, Exception("connection failed"))
    target = {
        "query": service.session.get,
        "flush": service.repository.create,
        "commit": service.session.commit,
    }[failure_stage]
    target.side_effect = error
    with pytest.raises(OperationalError) as caught:
        service.create(business_data)
    assert caught.value is error
    service.session.rollback.assert_called_once_with()
    if failure_stage != "commit":
        service.session.commit.assert_not_called()


@pytest.mark.parametrize("operation", ["create", "update"])
def test_refresh_failure_rolls_back_and_propagates(
    service: BusinessService, business_data: BusinessCreate, operation: str
) -> None:
    error = OperationalError("statement", {}, Exception("connection failed"))
    service.session.refresh.side_effect = error
    with pytest.raises(OperationalError) as caught:
        if operation == "create":
            service.create(business_data)
        else:
            service.update(business_id, BusinessUpdate(name="Updated"))
    assert caught.value is error
    service.session.commit.assert_called_once_with()
    service.session.rollback.assert_called_once_with()


def test_unexpected_write_error_is_rolled_back_without_being_hidden(
    service: BusinessService, business_data: BusinessCreate
) -> None:
    error = RuntimeError("unexpected failure")
    service.repository.create.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        service.create(business_data)
    assert caught.value is error
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.fixture
def database_session() -> Iterator[Session]:
    # Only isolated in-memory tables needed to exercise ORM session behavior.
    engine = create_engine("sqlite:///:memory:")
    try:
        BusinessCategory.__table__.create(engine)
        Business.__table__.create(engine)
        with Session(engine, autoflush=False, expire_on_commit=True) as session:
            session.add(BusinessCategory(id=1, name="Beauty"))
            session.commit()
            yield session
    finally:
        engine.dispose()


def test_created_business_can_be_serialized_after_session_closes(
    database_session: Session, business_data: BusinessCreate
) -> None:
    business = BusinessService(database_session).create(business_data)
    assert not (
        set(BusinessResponse.model_fields) & inspect(business).expired_attributes
    )
    database_session.close()

    response = BusinessResponse.model_validate(business)
    assert isinstance(response.id, UUID)
    assert response.id.version == 4
    assert response.name == "Studio"
    assert response.category_id == 1
    assert response.service_mode == business_data.service_mode


def test_update_reuses_loaded_business_and_returns_accessible_fields(
    database_session: Session, business_data: BusinessCreate
) -> None:
    service = BusinessService(database_session)
    business = service.create(business_data)
    business_id = business.id
    database_session.expunge_all()
    database_session.get = Mock(wraps=database_session.get)

    updated_business = service.update(
        business_id, BusinessUpdate(name="Updated", description=None)
    )

    database_session.get.assert_called_once_with(Business, business_id)
    assert not (
        set(BusinessResponse.model_fields)
        & inspect(updated_business).expired_attributes
    )
    database_session.close()
    response = BusinessResponse.model_validate(updated_business)
    assert response.id == business_id
    assert response.name == "Updated"
    assert response.description is None
    assert response.whatsapp == business_data.whatsapp
