from uuid import UUID

from sqlalchemy import Row, Select, func, or_, select
from sqlalchemy.orm import Session

from app.modules.businesses.models import Business
from app.modules.subscriptions.models import Plan, Subscription, SubscriptionStatus
from app.modules.users.models import User


class AdminRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _base() -> Select:
        # Outer joins: a business without a subscription or an owner still shows up.
        return (
            select(
                Business.id.label("business_id"),
                Business.name,
                User.email.label("owner_email"),
                User.name.label("owner_name"),
                Subscription.status,
                Subscription.trial_ends_at,
                Subscription.current_period_end,
                Subscription.grace_ends_at,
                Subscription.canceled_at,
                Plan.code.label("plan_code"),
                Plan.price_cents,
            )
            .select_from(Business)
            .outerjoin(User, User.business_id == Business.id)
            .outerjoin(Subscription, Subscription.business_id == Business.id)
            .outerjoin(Plan, Plan.id == Subscription.plan_id)
        )

    def list_businesses(
        self,
        *,
        status: SubscriptionStatus | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> list[Row]:
        statement = self._base()
        if status is not None:
            statement = statement.where(Subscription.status == status)
        if search:
            pattern = f"%{search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(Business.name).like(pattern),
                    func.lower(User.email).like(pattern),
                )
            )
        # Business.id breaks ties so pages never repeat or skip a row.
        statement = statement.order_by(Business.name, Business.id)
        return list(self.session.execute(statement.limit(limit).offset(offset)))

    def get_business(self, business_id: UUID) -> Row | None:
        return self.session.execute(
            self._base().where(Business.id == business_id)
        ).first()
