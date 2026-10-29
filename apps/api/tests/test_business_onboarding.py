from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.modules.auth.exceptions import InvalidAccessTokenError
from app.modules.businesses.exceptions import BusinessConflictError
from app.modules.businesses.repository import BusinessRepository
from app.modules.businesses.schemas import BusinessCreate
from app.modules.businesses.service import BusinessService
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


@pytest.fixture
def data() -> BusinessCreate:
    return BusinessCreate(
        name="Studio", category_id=1, whatsapp="85999999999", service_mode="HIBRIDO"
    )


@pytest.fixture
def service() -> BusinessService:
    service = BusinessService(Mock(spec=Session))
    service.repository = Mock(spec=BusinessRepository)
    service.user_repository = Mock(spec=UserRepository)
    service.user_repository.get_by_id_for_update.return_value = Mock(
        spec=User, business_id=None, is_active=True
    )
    return service


def test_onboarding_locks_user_links_business_and_commits_once(
    service: BusinessService, data: BusinessCreate
) -> None:
    user_id = uuid4()
    order = Mock()
    order.attach_mock(service.user_repository.update, "link")
    order.attach_mock(service.session.commit, "commit")

    result = service.create_for_user(data, user_id=user_id)

    service.user_repository.get_by_id_for_update.assert_called_once_with(user_id)
    service.repository.create.assert_called_once_with(data)
    service.user_repository.update.assert_called_once_with(
        service.user_repository.get_by_id_for_update.return_value, business_id=result.id
    )
    assert [call[0] for call in order.mock_calls] == ["link", "commit"]
    service.session.commit.assert_called_once_with()
    service.session.rollback.assert_not_called()


def test_existing_business_rechecked_under_lock_prevents_second_creation(
    service: BusinessService, data: BusinessCreate
) -> None:
    service.user_repository.get_by_id_for_update.return_value.business_id = uuid4()
    with pytest.raises(BusinessConflictError):
        service.create_for_user(data, user_id=uuid4())
    service.repository.create.assert_not_called()
    service.user_repository.update.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize("missing", [False, True])
def test_revoked_user_is_rechecked_under_lock(
    service: BusinessService, data: BusinessCreate, missing: bool
) -> None:
    if missing:
        service.user_repository.get_by_id_for_update.return_value = None
    else:
        service.user_repository.get_by_id_for_update.return_value.is_active = False
    with pytest.raises(InvalidAccessTokenError):
        service.create_for_user(data, user_id=uuid4())
    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


@pytest.mark.parametrize("stage", ["lock", "create", "link", "commit"])
@pytest.mark.parametrize("error_type", [IntegrityError, OperationalError, RuntimeError])
def test_onboarding_failures_roll_back_the_whole_transaction(
    service: BusinessService,
    data: BusinessCreate,
    stage: str,
    error_type: type[Exception],
) -> None:
    error = (
        error_type("sensitive SQL", {}, Exception("private detail"))
        if error_type is not RuntimeError
        else RuntimeError("failure")
    )
    target = {
        "lock": service.user_repository.get_by_id_for_update,
        "create": service.repository.create,
        "link": service.user_repository.update,
        "commit": service.session.commit,
    }[stage]
    target.side_effect = error
    expected = BusinessConflictError if error_type is IntegrityError else error_type
    with pytest.raises(expected) as caught:
        service.create_for_user(data, user_id=uuid4())
    service.session.rollback.assert_called_once_with()
    if stage != "commit":
        service.session.commit.assert_not_called()
    if error_type is IntegrityError:
        assert "private detail" not in str(caught.value)
    else:
        assert caught.value is error


def test_user_repository_emits_postgresql_row_lock_and_refreshes_identity_map() -> None:
    session = Mock(spec=Session)
    user_id = uuid4()
    UserRepository(session).get_by_id_for_update(user_id)
    statement = session.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert "users.id =" in sql
    assert user_id in statement.compile(dialect=postgresql.dialect()).params.values()
    assert statement.get_execution_options()["populate_existing"] is True
