from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.subscriptions.models import (
    GatewayEvent,
    Plan,
    Subscription,
    SubscriptionStatus,
)

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

    def list_trials_ended(self, now: datetime, limit: int) -> list[Subscription]:
        return self._locked_batch(
            Subscription.status == SubscriptionStatus.TRIALING,
            Subscription.trial_ends_at <= now,
            limit=limit,
        )

    def list_period_lapsed(self, now: datetime, limit: int) -> list[Subscription]:
        return self._locked_batch(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.current_period_end <= now,
            limit=limit,
        )

    def list_grace_ended(self, now: datetime, limit: int) -> list[Subscription]:
        return self._locked_batch(
            Subscription.status == SubscriptionStatus.PAST_DUE,
            Subscription.grace_ends_at <= now,
            limit=limit,
        )

    def _locked_batch(self, *conditions, limit: int) -> list[Subscription]:
        """Rows another run already holds are skipped, so two runs never overlap."""
        statement = (
            select(Subscription)
            .where(*conditions)
            .order_by(Subscription.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self.session.scalars(statement))

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
