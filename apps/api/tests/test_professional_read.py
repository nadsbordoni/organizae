from collections.abc import Iterator
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.exceptions import InvalidProfessionalPaginationError
from app.modules.professionals.models import Professional
from app.modules.professionals.repository import ProfessionalRepository
from app.modules.professionals.service import ProfessionalService


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    try:
        # Schema creation is restricted to this isolated in-memory test database.
        for table in Base.metadata.sorted_tables:
            table.create(engine)
        with Session(engine, autoflush=False) as session:
            yield session
    finally:
        engine.dispose()


def test_repository_isolates_business_and_filters_before_pagination(
    session: Session,
) -> None:
    category = BusinessCategory(name="Demo")
    session.add(category)
    session.flush()
    first, second = [
        Business(
            name=name,
            category_id=category.id,
            whatsapp="00000000000",
            service_mode=ServiceMode.PRESENCIAL,
        )
        for name in ("First", "Second")
    ]
    session.add_all([first, second])
    session.flush()
    professionals = [
        Professional(
            business_id=first.id,
            name=str(index),
            is_active=index != 0,
        )
        for index in range(4)
    ]
    other = Professional(business_id=second.id, name="Other", is_active=True)
    session.add_all([*professionals, other])
    session.flush()
    repository = ProfessionalRepository(session)
    session.commit = Mock()
    session.rollback = Mock()
    expected = sorted(professionals, key=lambda item: item.id)
    active = [item for item in expected if item.is_active]
    assert repository.list(business_id=first.id) == expected
    assert (
        repository.list(business_id=first.id, is_active=True, offset=1, limit=1)
        == active[1:2]
    )
    assert repository.list(business_id=first.id, is_active=False) == [professionals[0]]
    assert repository.list(business_id=second.id) == [other]
    assert repository.list(business_id=uuid4()) == []
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.parametrize("offset, limit", [(-1, 20), (0, 0), (0, 101)])
def test_service_rejects_invalid_pagination(offset: int, limit: int) -> None:
    service = ProfessionalService(Mock(spec=Session))
    service.repository = Mock(spec=ProfessionalRepository)
    with pytest.raises(InvalidProfessionalPaginationError):
        service.list(business_id=uuid4(), offset=offset, limit=limit)
    service.repository.list.assert_not_called()


def test_service_forwards_business_and_active_filter() -> None:
    service = ProfessionalService(Mock(spec=Session))
    service.repository = Mock(spec=ProfessionalRepository)
    service.repository.list.return_value = []
    business_id = uuid4()
    assert (
        service.list(business_id=business_id, is_active=False, offset=3, limit=5) == []
    )
    service.repository.list.assert_called_once_with(
        business_id=business_id,
        is_active=False,
        offset=3,
        limit=5,
    )
