from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.services.exceptions import (
    InvalidServicePaginationError,
    ServiceConflictError,
    ServiceNotFoundError,
)
from app.modules.services.models import Service
from app.modules.services.repository import ServiceRepository
from app.modules.services.schemas import ServiceCreate, ServiceUpdate


class ServiceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ServiceRepository(session)
        self.business_repository = BusinessRepository(session)

    def get_by_id(self, service_id: UUID, *, business_id: UUID) -> Service:
        service = self.repository.get_by_id(service_id, business_id=business_id)
        if service is None:
            raise ServiceNotFoundError("Service not found")
        return service

    def list(
        self, *, business_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[Service]:
        if offset < 0 or limit < 1:
            raise InvalidServicePaginationError(
                "offset must be non-negative and limit must be positive"
            )
        return self.repository.list(business_id=business_id, offset=offset, limit=limit)

    def create(self, service_data: ServiceCreate) -> Service:
        with self._transaction():
            if self.business_repository.get_by_id(service_data.business_id) is None:
                raise BusinessNotFoundError("Business not found")
            service = self.repository.create(service_data)
            self.session.commit()
            self.session.refresh(service)
        return service

    def update(
        self, service_id: UUID, service_data: ServiceUpdate, *, business_id: UUID
    ) -> Service:
        with self._transaction():
            service = self.get_by_id(service_id, business_id=business_id)
            service = self.repository.update(service, service_data)
            self.session.commit()
            self.session.refresh(service)
        return service

    def delete(self, service_id: UUID, *, business_id: UUID) -> None:
        with self._transaction():
            if not self.repository.delete(service_id, business_id=business_id):
                raise ServiceNotFoundError("Service not found")
            self.session.commit()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            raise ServiceConflictError(
                "Operation conflicts with related data or database constraints"
            ) from exc
        except Exception:
            # Cleanup must also cover unexpected errors without hiding them.
            self.session.rollback()
            raise
