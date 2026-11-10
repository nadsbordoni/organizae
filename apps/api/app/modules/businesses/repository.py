from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.modules.businesses.models import Business
from app.modules.businesses.schemas import BusinessCreate, BusinessUpdate
from app.modules.services.models import Service


class BusinessRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, business_data: BusinessCreate) -> Business:
        business = Business(**business_data.model_dump())
        self.session.add(business)
        self.session.flush()
        return business

    def get_by_id(self, business_id: UUID) -> Business | None:
        return self.session.get(Business, business_id)

    def list(
        self, *, business_id: UUID | None = None, offset: int = 0, limit: int = 100
    ) -> list[Business]:
        statement = select(Business)
        if business_id is not None:
            statement = statement.where(Business.id == business_id)
        statement = statement.order_by(Business.id).offset(offset).limit(limit)
        return list(self.session.scalars(statement).all())

    def update(self, business: Business, business_data: BusinessUpdate) -> Business:
        for field_name, field_value in business_data.model_dump(
            exclude_unset=True
        ).items():
            setattr(business, field_name, field_value)

        self.session.flush()
        return business

    def get_by_id_for_update(self, business_id: UUID) -> Business | None:
        statement = select(Business).where(Business.id == business_id).with_for_update()
        return self.session.scalars(statement).first()

    def get_published_by_slug(self, slug: str) -> Business | None:
        statement = select(Business).where(
            Business.slug == slug, Business.is_published.is_(True)
        )
        return self.session.scalars(statement).first()

    def slug_exists(self, slug: str) -> bool:
        return bool(self.session.scalar(select(exists().where(Business.slug == slug))))

    def has_active_services(self, business_id: UUID) -> bool:
        statement = select(
            exists().where(
                Service.business_id == business_id, Service.is_active.is_(True)
            )
        )
        return bool(self.session.scalar(statement))

    def list_active_services(self, business_id: UUID) -> list[Service]:
        statement = (
            select(Service)
            .where(Service.business_id == business_id, Service.is_active.is_(True))
            .order_by(Service.name)
        )
        return list(self.session.scalars(statement).all())

    def publish(
        self, business: Business, *, slug: str, published_at: datetime
    ) -> Business:
        business.slug = slug
        business.is_published = True
        business.published_at = published_at
        self.session.flush()
        return business

    def delete(self, business_id: UUID) -> bool:
        business = self.get_by_id(business_id)

        if business is None:
            return False

        self.session.delete(business)
        self.session.flush()
        return True
