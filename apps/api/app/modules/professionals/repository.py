from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from app.modules.professionals.models import Professional
from app.modules.professionals.schemas import (
    ProfessionalCreate,
    ProfessionalServicesUpdate,
    ProfessionalUpdate,
)
from app.modules.services.associations import professional_services


class ProfessionalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, professional_data: ProfessionalCreate) -> Professional:
        professional = Professional(
            **professional_data.model_dump(exclude={"service_ids"})
        )
        self.session.add(professional)
        self.session.flush()
        self._insert_services(professional, professional_data.service_ids)
        self.session.refresh(professional, attribute_names=["services"])
        return professional

    def get_by_id(
        self, professional_id: UUID, *, business_id: UUID
    ) -> Professional | None:
        statement = (
            select(Professional)
            .options(selectinload(Professional.services))
            .where(
                Professional.id == professional_id,
                Professional.business_id == business_id,
            )
        )
        return self.session.scalar(statement)

    def list(
        self, *, business_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[Professional]:
        statement = (
            select(Professional)
            .options(selectinload(Professional.services))
            .where(Professional.business_id == business_id)
            .order_by(Professional.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def update(
        self, professional: Professional, professional_data: ProfessionalUpdate
    ) -> Professional:
        for field_name, field_value in professional_data.model_dump(
            exclude_unset=True
        ).items():
            setattr(professional, field_name, field_value)
        self.session.flush()
        return professional

    def replace_services(
        self, professional: Professional, services_data: ProfessionalServicesUpdate
    ) -> Professional:
        self.session.execute(
            delete(professional_services).where(
                professional_services.c.professional_id == professional.id,
                professional_services.c.business_id == professional.business_id,
            )
        )
        self._insert_services(professional, services_data.service_ids)
        self.session.flush()
        # Core writes bypass the ORM collection, which may already be loaded.
        self.session.refresh(professional, attribute_names=["services"])
        return professional

    def delete(self, professional_id: UUID, *, business_id: UUID) -> bool:
        professional = self.get_by_id(professional_id, business_id=business_id)
        if professional is None:
            return False
        self.session.delete(professional)
        self.session.flush()
        return True

    def _insert_services(
        self, professional: Professional, service_ids: list[UUID]
    ) -> None:
        if service_ids:
            self.session.execute(
                insert(professional_services),
                [
                    {
                        "professional_id": professional.id,
                        "service_id": service_id,
                        "business_id": professional.business_id,
                    }
                    for service_id in service_ids
                ],
            )
