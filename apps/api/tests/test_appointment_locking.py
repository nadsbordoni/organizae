from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_appointments import (
    at,
    booking_at,
    business_id,
    now,
    professional_id,
    service,
)

from app.modules.appointments.exceptions import AppointmentConflictError
from app.modules.appointments.repository import AppointmentRepository
from app.modules.appointments.schemas import (
    AppointmentStatusUpdate,
    BlockCreateRequest,
    BusinessHoursUpdate,
)

__all__ = ["service"]


def test_lock_uses_the_same_business_row_in_postgresql():
    session = Mock(spec=Session)
    AppointmentRepository(session).lock_business(business_id)
    statement = session.scalar.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(compiled)
    assert "businesses.id =" in str(compiled)
    assert business_id in compiled.params.values()


@pytest.mark.parametrize("operation", ["panel", "online", "block", "hours", "status"])
def test_every_agenda_write_locks_before_reading_rules_or_writing(service, operation):
    repository = service.repository
    if operation in ("panel", "online"):
        method = service.book_panel if operation == "panel" else service.book_online
        method(booking_at(at(9)), business_id=business_id, now=now)
    elif operation == "block":
        service.create_block(
            BlockCreateRequest(
                professional_id=professional_id, starts_at=at(9), ends_at=at(10)
            ),
            business_id=business_id,
        )
    elif operation == "hours":
        service.replace_hours(BusinessHoursUpdate(hours=[]), business_id=business_id)
    else:
        service.update_status(
            professional_id,
            AppointmentStatusUpdate(status="CONFIRMED"),
            business_id=business_id,
        )
    assert repository.mock_calls[0][0] == "lock_business"
    repository.lock_business.assert_called_once_with(business_id)
    service.session.commit.assert_called_once_with()


@pytest.mark.parametrize("professional", [None, professional_id])
def test_overlapping_blocks_are_refused_without_writing(service, professional):
    service.repository.has_overlap.return_value = True
    with pytest.raises(AppointmentConflictError):
        service.create_block(
            BlockCreateRequest(
                professional_id=professional, starts_at=at(9), ends_at=at(10)
            ),
            business_id=business_id,
        )
    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_lock_failure_rolls_back_without_attempting_availability_or_insert(service):
    failure = OperationalError("private query", {}, Exception("private"))
    service.repository.lock_business.side_effect = failure
    with pytest.raises(OperationalError) as error:
        service.book_panel(booking_at(at(9)), business_id=business_id, now=now)
    assert error.value is failure
    service.repository.get_bookable_service.assert_not_called()
    service.repository.create.assert_not_called()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()
