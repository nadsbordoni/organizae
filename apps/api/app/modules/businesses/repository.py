from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.businesses.models import Business
from app.modules.businesses.schemas import BusinessCreate, BusinessUpdate


class BusinessRepository:

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, business_data: BusinessCreate) -> Business:
        business = Business(**business_data.model_dump())
        self.session.add(business)
        self.session.flush()
        return business

    def get_by_id(self, business_id: int) -> Business | None:
        return self.session.get(Business, business_id)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[Business]:
        statement = (
            select(Business)
            .order_by(Business.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def update(
        self, business_id: int, business_data: BusinessUpdate
    ) -> Business | None:
        business = self.get_by_id(business_id)

        if business is None:
            return None

        for field_name, field_value in business_data.model_dump(
            exclude_unset=True
        ).items():
            setattr(business, field_name, field_value)

        self.session.flush()
        return business

    def delete(self, business_id: int) -> bool:
        business = self.get_by_id(business_id)

        if business is None:
            return False

        self.session.delete(business)
        self.session.flush()
        return True