from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.modules.clients.exceptions import (
    ClientConflictError,
    ClientNotFoundError,
    InvalidClientPaginationError,
)
from app.modules.clients.models import Client
from app.modules.clients.repository import ClientRepository
from app.modules.clients.schemas import ClientCreate, ClientUpdate
from app.modules.clients.service import ClientService

business_id, client_id = uuid4(), uuid4()


@pytest.fixture
def service() -> ClientService:
    service = ClientService(Mock(spec=Session))
    service.repository = Mock(spec=ClientRepository)
    service.repository.get_by_phone.return_value = None
    service.repository.get_by_id.return_value = Client(
        id=client_id, business_id=business_id, name="Client", phone="85999999999"
    )
    return service


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("failure", ["lookup", "write", "commit"])
@pytest.mark.parametrize("error_type", [IntegrityError, OperationalError, RuntimeError])
def test_transaction_failures_roll_back_and_preserve_unexpected_errors(
    service: ClientService, operation: str, failure: str, error_type: type[Exception]
) -> None:
    error = (
        error_type("private statement", {}, Exception("private details"))
        if error_type in (IntegrityError, OperationalError)
        else error_type("private details")
    )
    target = {
        "lookup": service.repository.get_by_phone,
        "write": getattr(service.repository, operation),
        "commit": service.session.commit,
    }[failure]
    target.side_effect = error
    with pytest.raises(
        ClientConflictError if error_type is IntegrityError else error_type
    ) as caught:
        if operation == "create":
            service.create(
                ClientCreate(name="New client", phone="85988887777"),
                business_id=business_id,
            )
        else:
            service.update(
                client_id, ClientUpdate(phone="85988887777"), business_id=business_id
            )
    service.session.rollback.assert_called_once_with()
    if failure != "commit":
        service.session.commit.assert_not_called()
    if error_type is not IntegrityError:
        assert caught.value is error
    else:
        assert "private" not in str(caught.value)


def test_missing_client_update_rolls_back_without_writing(
    service: ClientService,
) -> None:
    service.repository.get_by_id.return_value = None
    with pytest.raises(ClientNotFoundError):
        service.update(
            client_id, ClientUpdate(name="New name"), business_id=business_id
        )
    service.repository.update.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_update_loads_client_once_and_skips_phone_lookup_when_unchanged(
    service: ClientService,
) -> None:
    service.update(
        client_id, ClientUpdate(phone="(85) 99999-9999"), business_id=business_id
    )
    service.repository.get_by_id.assert_called_once_with(
        client_id, business_id=business_id
    )
    service.repository.get_by_phone.assert_not_called()
    service.session.commit.assert_called_once_with()


@pytest.mark.parametrize("operation", ["list", "list_appointments"])
@pytest.mark.parametrize(("offset", "limit"), [(-1, 100), (0, 0), (0, 101)])
def test_invalid_pagination_is_rejected_before_query(
    service: ClientService, operation: str, offset: int, limit: int
) -> None:
    with pytest.raises(InvalidClientPaginationError):
        if operation == "list":
            service.list(business_id=business_id, offset=offset, limit=limit)
        else:
            service.list_appointments(
                client_id, business_id=business_id, offset=offset, limit=limit
            )
    service.repository.get_by_id.assert_not_called()
    service.repository.list.assert_not_called()
    service.repository.list_appointments.assert_not_called()
    service.session.commit.assert_not_called()


def test_history_checks_client_ownership_before_loading_appointments(
    service: ClientService,
) -> None:
    service.repository.get_by_id.return_value = None
    with pytest.raises(ClientNotFoundError):
        service.list_appointments(client_id, business_id=business_id)
    service.repository.list_appointments.assert_not_called()
