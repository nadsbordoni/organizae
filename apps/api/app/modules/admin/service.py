from uuid import UUID

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.modules.admin.repository import AdminRepository
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.subscriptions.models import SubscriptionStatus


class AdminService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AdminRepository(session)

    def list_businesses(
        self,
        *,
        status: SubscriptionStatus | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> list[Row]:
        return self.repository.list_businesses(
            status=status, search=search, limit=limit, offset=offset
        )

    def get_business(self, business_id: UUID) -> Row:
        row = self.repository.get_business(business_id)
        if row is None:
            raise BusinessNotFoundError("Business not found")
        return row
