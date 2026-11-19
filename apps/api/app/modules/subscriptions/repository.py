from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.subscriptions.models import GatewayEvent, Plan, Subscription

DEFAULT_PLAN_CODE = "standard"


class SubscriptionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_business_id(self, business_id: UUID) -> Subscription | None:
        return self.session.scalar(
            select(Subscription).where(Subscription.business_id == business_id)
        )

    def get_for_update(self, business_id: UUID) -> Subscription | None:
        return self.session.scalar(
            select(Subscription)
            .where(Subscription.business_id == business_id)
            .with_for_update()
        )

    def get_by_gateway_subscription_id(
        self, gateway_subscription_id: str
    ) -> Subscription | None:
        return self.session.scalar(
            select(Subscription)
            .where(Subscription.gateway_subscription_id == gateway_subscription_id)
            .with_for_update()
        )

    def record_event(self, event_id: str) -> bool:
        """Remembers a webhook event; False when it was already handled."""
        if self.session.get(GatewayEvent, event_id) is not None:
            return False
        self.session.add(GatewayEvent(event_id=event_id))
        self.session.flush()
        return True

    def get_plan(self, plan_id: UUID) -> Plan:
        return self.session.get(Plan, plan_id)

    def add(self, subscription: Subscription) -> Subscription:
        self.session.add(subscription)
        self.session.flush()
        return subscription

    def delete_by_business_id(self, business_id: UUID) -> None:
        self.session.execute(
            delete(Subscription).where(Subscription.business_id == business_id)
        )

    def get_default_plan(self) -> Plan:
        return self.session.scalars(
            select(Plan).where(Plan.code == DEFAULT_PLAN_CODE)
        ).one()
