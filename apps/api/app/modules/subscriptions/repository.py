from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.subscriptions.models import Plan, Subscription

DEFAULT_PLAN_CODE = "standard"


class SubscriptionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_business_id(self, business_id: UUID) -> Subscription | None:
        return self.session.scalar(
            select(Subscription).where(Subscription.business_id == business_id)
        )

    def add(self, subscription: Subscription) -> Subscription:
        self.session.add(subscription)
        self.session.flush()
        return subscription

    def get_default_plan(self) -> Plan:
        return self.session.scalars(
            select(Plan).where(Plan.code == DEFAULT_PLAN_CODE)
        ).one()
