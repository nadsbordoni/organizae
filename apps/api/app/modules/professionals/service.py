from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.repository import BusinessRepository
from app.modules.professionals.exceptions import (
    InvalidProfessionalPaginationError,
    InvalidProfessionalServicesError,
    ProfessionalConflictError,
    ProfessionalNotFoundError,
)
from app.modules.professionals.models import Professional
from app.modules.professionals.repository import ProfessionalRepository
from app.modules.professionals.schemas import (
    ProfessionalCreate,
    ProfessionalServicesUpdate,
    ProfessionalUpdate,
)
from app.modules.services.repository import ServiceRepository


class ProfessionalService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ProfessionalRepository(session)
        self.business_repository = BusinessRepository(session)
        self.service_repository = ServiceRepository(session)

    def get_by_id(self, professional_id: UUID, *, business_id: UUID) -> Professional:
        professional = self.repository.get_by_id(
            professional_id, business_id=business_id
        )
        if professional is None:
            raise ProfessionalNotFoundError("Professional not found")
        return professional

    def list(
        self,
        *,
        business_id: UUID,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Professional]:
        if offset < 0 or not 1 <= limit <= 100:
            raise InvalidProfessionalPaginationError(
                "offset must be non-negative and limit must be between 1 and 100"
            )
        return self.repository.list(
            business_id=business_id, is_active=is_active, offset=offset, limit=limit
        )

    def create(self, professional_data: ProfessionalCreate) -> Professional:
        with self._transaction():
            if (
                self.business_repository.get_by_id(professional_data.business_id)
                is None
            ):
                raise BusinessNotFoundError("Business not found")
            self._validate_services(
                professional_data.service_ids, business_id=professional_data.business_id
            )
            professional = self.repository.create(professional_data)
            self._commit_and_refresh(professional)
        return professional

    def update(
        self,
        professional_id: UUID,
        professional_data: ProfessionalUpdate,
        *,
        business_id: UUID,
    ) -> Professional:
        with self._transaction():
            professional = self.get_by_id(professional_id, business_id=business_id)
            professional = self.repository.update(professional, professional_data)
            self._commit_and_refresh(professional)
        return professional

    def replace_services(
        self,
        professional_id: UUID,
        services_data: ProfessionalServicesUpdate,
        *,
        business_id: UUID,
    ) -> Professional:
        with self._transaction():
            professional = self.get_by_id(professional_id, business_id=business_id)
            self._validate_services(services_data.service_ids, business_id=business_id)
            professional = self.repository.replace_services(professional, services_data)
            self._commit_and_refresh(professional)
        return professional

    def delete(self, professional_id: UUID, *, business_id: UUID) -> None:
        with self._transaction():
            professional = self.get_by_id(professional_id, business_id=business_id)
            self.repository.update(professional, ProfessionalUpdate(is_active=False))
            self.session.commit()

    def _validate_services(self, service_ids: list[UUID], *, business_id: UUID) -> None:
        if len(service_ids) != len(set(service_ids)):
            raise InvalidProfessionalServicesError(
                "service_ids must not contain duplicates"
            )
        for service_id in service_ids:
            if (
                self.service_repository.get_by_id(service_id, business_id=business_id)
                is None
            ):
                raise InvalidProfessionalServicesError(
                    "One or more services were not found in this business"
                )

    def _commit_and_refresh(self, professional: Professional) -> None:
        self.session.commit()
        self.session.refresh(professional)
        # The response includes services even after the request session closes.
        self.session.refresh(professional, attribute_names=["services"])

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            raise ProfessionalConflictError(
                "Operation conflicts with related data or database constraints"
            ) from exc
        except Exception:
            # Clean up unexpected errors while preserving their original type.
            self.session.rollback()
            raise
