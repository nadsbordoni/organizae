import calendar
import logging
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from math import ceil
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.subscriptions.exceptions import (
    GatewayError,
    InvalidSubscriptionTransitionError,
    SubscriptionNotFoundError,
)
from app.modules.subscriptions.gateway import PaymentGateway
from app.modules.subscriptions.models import Subscription, SubscriptionStatus
from app.modules.subscriptions.repository import SubscriptionRepository

logger = logging.getLogger(__name__)

DEFAULT_TRIAL_DAYS = 15
DEFAULT_GRACE_DAYS = 5
PAID_EVENTS = frozenset({"PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"})
OVERDUE_EVENT = "PAYMENT_OVERDUE"

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


class EventResult(str, Enum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


def add_month(start: date) -> date:
    """The same day next month, or the last day of a shorter month."""
    year, month = divmod(start.year * 12 + start.month, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


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
        period_end = subscription.current_period_end
        # A paid period nobody renewed does not last forever.
        if (
            status == S.ACTIVE
            and period_end is not None
            and has_passed(to_utc(period_end) + timedelta(days=self.grace_days), now)
        ):
            return AccessLevel.READ_ONLY
        return AccessLevel.FULL

    def process_due(self, *, now: datetime, batch_size: int = 500) -> dict[str, int]:
        """Moves forward what time alone has made overdue; commits per batch.

        Order matters: an ACTIVE business whose period and grace both ended
        goes through PAST_DUE and is suspended in the same run.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        return {
            "trial_suspended": self._drain(
                self.repository.list_trials_ended, self._suspend, now, batch_size
            ),
            "period_lapsed": self._drain(
                self.repository.list_period_lapsed, self._lapse, now, batch_size
            ),
            "grace_suspended": self._drain(
                self.repository.list_grace_ended, self._suspend, now, batch_size
            ),
        }

    def _drain(self, fetch, apply, now: datetime, batch_size: int) -> int:
        handled = 0
        while True:
            batch = fetch(now, batch_size)
            if not batch:
                return handled
            try:
                for subscription in batch:
                    apply(subscription)
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise
            handled += len(batch)
            if len(batch) < batch_size:
                return handled

    def _suspend(self, subscription: Subscription) -> None:
        self._move(subscription, S.SUSPENDED)

    def _lapse(self, subscription: Subscription) -> None:
        self._move(subscription, S.PAST_DUE)
        # Grace counts from when the period ended, not from when the job ran.
        subscription.grace_ends_at = to_utc(subscription.current_period_end) + timedelta(
            days=self.grace_days
        )

    def overview(self, business_id: UUID, *, now: datetime) -> dict:
        subscription = self.repository.get_by_business_id(business_id)
        if subscription is None:
            raise SubscriptionNotFoundError
        deadline = {
            S.TRIALING: subscription.trial_ends_at,
            S.ACTIVE: subscription.current_period_end,
            S.PAST_DUE: subscription.grace_ends_at,
        }.get(subscription.status)
        days_left = None
        if deadline is not None:
            seconds = (to_utc(deadline) - to_utc(now)).total_seconds()
            days_left = max(0, ceil(seconds / 86400))
        return {
            "status": subscription.status,
            "trial_ends_at": subscription.trial_ends_at,
            "current_period_end": subscription.current_period_end,
            "grace_ends_at": subscription.grace_ends_at,
            "days_left": days_left,
            "price_cents": self.repository.get_plan(subscription.plan_id).price_cents,
        }

    def start_checkout(
        self,
        business_id: UUID,
        *,
        customer_name: str,
        customer_email: str,
        gateway: PaymentGateway,
        now: datetime,
    ) -> str:
        """Returns the link where the business pays; commits on its own.

        The row stays locked while the gateway is called, so two clicks cannot
        create two subscriptions there. What the gateway already accepted is
        saved even if a later step fails, so a retry does not duplicate it.
        """
        subscription = self._locked(business_id)
        if subscription.status == S.ACTIVE:
            raise InvalidSubscriptionTransitionError("Nothing to pay: already active")
        try:
            if subscription.gateway_subscription_id is not None:
                url = gateway.get_payment_url(subscription.gateway_subscription_id)
                if url is None:
                    raise GatewayError("The gateway returned no payment link")
            else:
                if subscription.gateway_customer_id is None:
                    subscription.gateway_customer_id = gateway.create_customer(
                        name=customer_name,
                        email=customer_email,
                        external_id=str(business_id),
                    )
                plan = self.repository.get_plan(subscription.plan_id)
                subscription_id, url = gateway.create_subscription(
                    customer_id=subscription.gateway_customer_id,
                    price_cents=plan.price_cents,
                    first_due=self._first_due(subscription, now),
                    external_id=str(business_id),
                )
                subscription.gateway_subscription_id = subscription_id
        except GatewayError:
            self.session.commit()
            raise
        except Exception:
            self.session.rollback()
            raise
        self.session.commit()
        return url

    def release_gateway_subscription(
        self, business_id: UUID, *, gateway: PaymentGateway
    ) -> None:
        """Stops the charges at the gateway; commits on its own.

        The id is kept when the gateway fails, so the call can be repeated.
        """
        subscription = self._locked(business_id)
        if subscription.gateway_subscription_id is None:
            self.session.rollback()
            return
        try:
            gateway.cancel_subscription(subscription.gateway_subscription_id)
        except Exception:
            self.session.rollback()
            raise
        subscription.gateway_subscription_id = None
        self.session.commit()

    def handle_gateway_event(
        self,
        *,
        event_id: str,
        event_type: str,
        gateway_subscription_id: str | None,
        due_date: date | None,
        now: datetime,
    ) -> EventResult:
        """Applies one webhook event once; commits on its own."""
        if event_type not in PAID_EVENTS and event_type != OVERDUE_EVENT:
            return EventResult.IGNORED
        if gateway_subscription_id is None:
            return EventResult.IGNORED
        try:
            subscription = self.repository.get_by_gateway_subscription_id(
                gateway_subscription_id
            )
            if subscription is None:
                logger.warning("Webhook for an unknown subscription: %s", event_id)
                return EventResult.IGNORED
            if not self.repository.record_event(event_id):
                self.session.rollback()
                return EventResult.DUPLICATE
            result = self._apply_event(subscription, event_type, due_date, now)
            self.session.commit()
            return result
        except IntegrityError:
            # Two copies of the same event raced: the other one won.
            self.session.rollback()
            return EventResult.DUPLICATE
        except Exception:
            self.session.rollback()
            raise

    def _apply_event(
        self,
        subscription: Subscription,
        event_type: str,
        due_date: date | None,
        now: datetime,
    ) -> EventResult:
        if event_type in PAID_EVENTS:
            charged = due_date or to_utc(now).date()
            paid_until = datetime.combine(add_month(charged), time(), tzinfo=UTC)
            self.mark_paid(subscription.business_id, paid_until=paid_until, now=now)
            return EventResult.APPLIED
        # An overdue notice for a charge the period already covers is stale
        # (it arrived after the payment, or out of order).
        covered_until = subscription.current_period_end
        if (
            due_date is not None
            and covered_until is not None
            and to_utc(covered_until).date() > due_date
        ):
            return EventResult.IGNORED
        try:
            self.mark_overdue(subscription.business_id, now=now)
        except InvalidSubscriptionTransitionError:
            return EventResult.IGNORED
        return EventResult.APPLIED

    def _first_due(self, subscription: Subscription, now: datetime) -> date:
        today = to_utc(now).date()
        ends = subscription.trial_ends_at
        if subscription.status == S.TRIALING and ends is not None:
            return max(today, to_utc(ends).date())
        return today

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
