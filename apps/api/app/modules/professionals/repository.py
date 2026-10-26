from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.professionals.models import Professional


class ProfessionalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self,
        *,
        business_id: UUID,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Professional]:
        statement = select(Professional).where(Professional.business_id == business_id)
        if is_active is not None:
            statement = statement.where(Professional.is_active == is_active)
        statement = statement.order_by(Professional.id).offset(offset).limit(limit)
        return list(self.session.scalars(statement).all())
