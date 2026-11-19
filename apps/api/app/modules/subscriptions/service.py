from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.subscriptions.exceptions import (
    InvalidSubscriptionTransitionError,
    SubscriptionNotFoundError,
)
from app.modules.subscriptions.models import Subscription, SubscriptionStatus
from app.modules.subscriptions.repository import SubscriptionRepository

DEFAULT_TRIAL_DAYS = 15
DEFAULT_GRACE_DAYS = 5

S = SubscriptionStatus
# Moving to the status a subscription already has is always a harmless no-op.
ALLOWED_TRANSITIONS: dict[S, set[S]] = {
    S.TRIALING: {S.ACTIVE, S.SUSPENDED, S.CANCELED},
    S.ACTIVE: {S.PAST_DUE, S.SUSPENDED, S.CANCELED},
    S.PAST_DUE: {S.ACTIVE, S.SUSPENDED, S.CANCELED},
    # SUSPENDED -> TRIALING is only reachable through extend_trial.
    S.SUSPENDED: {S.ACTIVE, S.CANCELED, S.TRIALING},
    S.CANCELED: {S.ACTIVE},
}


class AccessLevel(str, Enum):
    FULL = "FULL"
    READ_ONLY = "READ_ONLY"
    NONE = "NONE"


def to_utc(value: datetime) -> datetime:
    # The database may hand back naive values; they are always stored as UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def has_passed(deadline: datetime | None, now: datetime) -> bool:
    return deadline is not None and to_utc(deadline) <= to_utc(now)


class SubscriptionService:
    """Subscription state machine. The caller owns the transaction."""

    def __init__(
        self,
        session: Session,
        *,
        trial_days: int = DEFAULT_TRIAL_DAYS,
        grace_days: int = DEFAULT_GRACE_DAYS,
    ) -> None:
        self.session = session
        self.repository = SubscriptionRepository(session)
        self.trial_days = trial_days
        self.grace_days = grace_days

    def start_trial(self, business_id: UUID, *, now: datetime) -> Subscription:
        existing = self.repository.get_for_update(business_id)
        if existing is not None:
            return existing
        plan = self.repository.get_default_plan()
        return self.repository.add(
            Subscription(
                business_id=business_id,
                plan_id=plan.id,
                status=S.TRIALING,
                trial_ends_at=now + timedelta(days=self.trial_days),
            )
        )

    def mark_paid(
        self, business_id: UUID, *, paid_until: datetime, now: datetime
    ) -> Subscription:
        subscription = self._locked(business_id)
        self._move(subscription, S.ACTIVE)
        current = subscription.current_period_end
        if current is None or to_utc(current) < to_utc(paid_until):
            subscription.current_period_end = paid_until
        subscription.grace_ends_at = None
        subscription.canceled_at = None
        return subscription

    def extend_trial(
        self, business_id: UUID, *, days: int, now: datetime
    ) -> Subscription:
        """Gives a trial (or a suspended business) more days to try the product.

        Counts from the current end, or from now when the trial already ended.
        """
        if days < 1:
            raise ValueError("days must be at least 1")
        subscription = self._locked(business_id)
        # Only TRIALING and SUSPENDED may go (or stay) TRIALING; the rest raise.
        self._move(subscription, S.TRIALING)
        current = subscription.trial_ends_at
        start = now if current is None or to_utc(current) < to_utc(now) else current
        subscription.trial_ends_at = start + timedelta(days=days)
        return subscription

    def mark_overdue(self, business_id: UUID, *, now: datetime) -> Subscription:
        subscription = self._locked(business_id)
        if self._move(subscription, S.PAST_DUE):
            subscription.grace_ends_at = now + timedelta(days=self.grace_days)
        return subscription

    def suspend(self, business_id: UUID, *, now: datetime) -> Subscription:
        subscription = self._locked(business_id)
        self._move(subscription, S.SUSPENDED)
        return subscription

    def cancel(self, business_id: UUID, *, now: datetime) -> Subscription:
        subscription = self._locked(business_id)
        if self._move(subscription, S.CANCELED):
            subscription.canceled_at = now
        return subscription

    def access_level(
        self, subscription: Subscription | None, *, now: datetime
    ) -> AccessLevel:
        """What the business may do right now.

        Deadlines are checked here too, so access does not depend on the daily
        job having already run.
        """
        if subscription is None:
            return AccessLevel.FULL
        status = subscription.status
        if status == S.CANCELED:
            return AccessLevel.NONE
        if status == S.SUSPENDED:
            return AccessLevel.READ_ONLY
        if status == S.TRIALING and has_passed(subscription.trial_ends_at, now):
            return AccessLevel.READ_ONLY
        if status == S.PAST_DUE and has_passed(subscription.grace_ends_at, now):
            return AccessLevel.READ_ONLY
        return AccessLevel.FULL

    def _locked(self, business_id: UUID) -> Subscription:
        subscription = self.repository.get_for_update(business_id)
        if subscription is None:
            raise SubscriptionNotFoundError
        return subscription

    @staticmethod
    def _move(subscription: Subscription, target: SubscriptionStatus) -> bool:
        if subscription.status == target:
            return False
        if target not in ALLOWED_TRANSITIONS[subscription.status]:
            raise InvalidSubscriptionTransitionError(
                f"{subscription.status.value} -> {target.value}"
            )
        subscription.status = target
        return True
