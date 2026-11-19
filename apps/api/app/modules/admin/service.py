from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.modules.admin.repository import AdminRepository
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.subscriptions.models import SubscriptionStatus
from app.modules.subscriptions.service import SubscriptionService


class AdminService:
    def __init__(
        self, session: Session, subscriptions: SubscriptionService | None = None
    ) -> None:
        self.session = session
        self.repository = AdminRepository(session)
        self.subscriptions = subscriptions or SubscriptionService(session)

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

    def extend_trial(self, business_id: UUID, *, days: int) -> Row:
        with self._transaction():
            self.subscriptions.extend_trial(
                business_id, days=days, now=datetime.now(UTC)
            )
            self.session.commit()
        return self.get_business(business_id)

    def suspend(self, business_id: UUID) -> Row:
        with self._transaction():
            self.subscriptions.suspend(business_id, now=datetime.now(UTC))
            self.session.commit()
        return self.get_business(business_id)

    def reactivate(self, business_id: UUID, *, days: int) -> Row:
        now = datetime.now(UTC)
        with self._transaction():
            self.subscriptions.mark_paid(
                business_id, paid_until=now + timedelta(days=days), now=now
            )
            self.session.commit()
        return self.get_business(business_id)

    def cancel(self, business_id: UUID) -> Row:
        with self._transaction():
            self.subscriptions.cancel(business_id, now=datetime.now(UTC))
            self.session.commit()
        return self.get_business(business_id)

    def metrics(self) -> dict:
        counts = self.repository.count_by_status()
        return {
            "counts_by_status": {
                status: counts.get(status, 0) for status in SubscriptionStatus
            },
            "mrr_cents": self.repository.paying_total_cents(),
        }

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            # Undo the partial write and let the original error through.
            self.session.rollback()
            raise
