from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.services.models import Service
from app.modules.services.schemas import ServiceCreate, ServiceUpdate


class ServiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, service_data: ServiceCreate) -> Service:
        service = Service(**service_data.model_dump())
        self.session.add(service)
        self.session.flush()
        return service

    def get_by_id(self, service_id: UUID, *, business_id: UUID) -> Service | None:
        statement = select(Service).where(
            Service.id == service_id, Service.business_id == business_id
        )
        return self.session.scalar(statement)

    def list(
        self, *, business_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[Service]:
        statement = (
            select(Service)
            .where(Service.business_id == business_id)
            .order_by(Service.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def update(self, service: Service, service_data: ServiceUpdate) -> Service:
        for field_name, field_value in service_data.model_dump(
            exclude_unset=True
        ).items():
            setattr(service, field_name, field_value)

        self.session.flush()
        return service

    def delete(self, service_id: UUID, *, business_id: UUID) -> bool:
        service = self.get_by_id(service_id, business_id=business_id)
        if service is None:
            return False

        self.session.delete(service)
        self.session.flush()
        return True
