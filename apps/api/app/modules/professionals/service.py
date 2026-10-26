from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.professionals.exceptions import InvalidProfessionalPaginationError
from app.modules.professionals.models import Professional
from app.modules.professionals.repository import ProfessionalRepository


class ProfessionalService:
    def __init__(self, session: Session) -> None:
        self.repository = ProfessionalRepository(session)

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
            business_id=business_id,
            is_active=is_active,
            offset=offset,
            limit=limit,
        )
