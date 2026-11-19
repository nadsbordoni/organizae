from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.modules.subscriptions.exceptions import (
    InvalidSubscriptionTransitionError,
    SubscriptionNotFoundError,
)
from app.modules.subscriptions.models import Plan, Subscription, SubscriptionStatus
from app.modules.subscriptions.repository import SubscriptionRepository
from app.modules.subscriptions.service import AccessLevel, SubscriptionService

S = SubscriptionStatus
business_id = uuid4()
now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

# Every status may stay where it is (idempotent) or move to these.
ALLOWED = {
    S.TRIALING: {S.ACTIVE, S.SUSPENDED, S.CANCELED},
    S.ACTIVE: {S.PAST_DUE, S.SUSPENDED, S.CANCELED},
    S.PAST_DUE: {S.ACTIVE, S.SUSPENDED, S.CANCELED},
    S.SUSPENDED: {S.ACTIVE, S.CANCELED},
    S.CANCELED: {S.ACTIVE},
}
ACTIONS = {
    "mark_paid": S.ACTIVE,
    "mark_overdue": S.PAST_DUE,
    "suspend": S.SUSPENDED,
    "cancel": S.CANCELED,
}


def subscription(status: S, **overrides: object) -> Subscription:
    values = {
        "id": uuid4(),
        "business_id": business_id,
        "plan_id": uuid4(),
        "status": status,
    }
    return Subscription(**{**values, **overrides})


@pytest.fixture
def service() -> SubscriptionService:
    instance = SubscriptionService(Mock(spec=Session))
    instance.repository = Mock(spec=SubscriptionRepository)
    instance.repository.get_default_plan.return_value = Plan(
        id=uuid4(), code="standard", name="Organizaê", price_cents=4990
    )
    instance.repository.add.side_effect = lambda item: item
    return instance


def act(
    service: SubscriptionService, action: str, current: Subscription | None
) -> Subscription:
    service.repository.get_for_update.return_value = current
    if action == "mark_paid":
        return service.mark_paid(
            business_id, paid_until=now + timedelta(days=30), now=now
        )
    return getattr(service, action)(business_id, now=now)


def test_start_trial_uses_the_configured_days(service: SubscriptionService) -> None:
    service.repository.get_for_update.return_value = None
    created = service.start_trial(business_id, now=now)
    assert created.status == S.TRIALING
    assert created.trial_ends_at == now + timedelta(days=15)
    assert created.business_id == business_id
    service.repository.add.assert_called_once()


def test_start_trial_honors_a_custom_length() -> None:
    custom = SubscriptionService(Mock(spec=Session), trial_days=7)
    custom.repository = Mock(spec=SubscriptionRepository)
    custom.repository.get_for_update.return_value = None
    custom.repository.add.side_effect = lambda item: item
    assert custom.start_trial(business_id, now=now).trial_ends_at == now + timedelta(
        days=7
    )


def test_start_trial_is_idempotent(service: SubscriptionService) -> None:
    existing = subscription(S.ACTIVE)
    service.repository.get_for_update.return_value = existing
    assert service.start_trial(business_id, now=now) is existing
    service.repository.add.assert_not_called()


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("current", list(S))
def test_transition_table(
    service: SubscriptionService, current: S, action: str
) -> None:
    target = ACTIONS[action]
    record = subscription(current)
    if target in ALLOWED[current]:
        assert act(service, action, record).status == target
    elif target == current:
        # Repeating an action (or renewing an active plan) changes nothing.
        assert act(service, action, record).status == current
    else:
        with pytest.raises(InvalidSubscriptionTransitionError):
            act(service, action, record)
        assert record.status == current


@pytest.mark.parametrize("action", ACTIONS)
def test_unknown_subscription_is_reported(
    service: SubscriptionService, action: str
) -> None:
    with pytest.raises(SubscriptionNotFoundError):
        act(service, action, None)


def test_mark_overdue_sets_grace_end_to_now_plus_grace_days(
    service: SubscriptionService,
) -> None:
    record = act(service, "mark_overdue", subscription(S.ACTIVE))
    assert record.grace_ends_at == now + timedelta(days=5)


def test_repeated_overdue_does_not_extend_the_grace_period(
    service: SubscriptionService,
) -> None:
    record = subscription(S.PAST_DUE, grace_ends_at=now + timedelta(days=1))
    act(service, "mark_overdue", record)
    assert record.grace_ends_at == now + timedelta(days=1)


def test_mark_paid_reactivates_a_suspended_subscription(
    service: SubscriptionService,
) -> None:
    record = subscription(
        S.SUSPENDED, grace_ends_at=now - timedelta(days=1), canceled_at=None
    )
    paid = act(service, "mark_paid", record)
    assert paid.status == S.ACTIVE
    assert paid.current_period_end == now + timedelta(days=30)
    assert paid.grace_ends_at is None


def test_mark_paid_never_moves_the_period_backwards(
    service: SubscriptionService,
) -> None:
    later = now + timedelta(days=60)
    record = subscription(S.ACTIVE, current_period_end=later)
    assert act(service, "mark_paid", record).current_period_end == later


def test_cancel_records_when_and_reactivation_clears_it(
    service: SubscriptionService,
) -> None:
    record = subscription(S.ACTIVE)
    assert act(service, "cancel", record).canceled_at == now
    assert act(service, "mark_paid", record).canceled_at is None


def test_transitions_lock_the_row_and_never_commit(
    service: SubscriptionService,
) -> None:
    act(service, "suspend", subscription(S.ACTIVE))
    service.repository.get_for_update.assert_called_once_with(business_id)
    service.session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("current", "level"),
    [
        (S.TRIALING, AccessLevel.FULL),
        (S.ACTIVE, AccessLevel.FULL),
        (S.PAST_DUE, AccessLevel.FULL),
        (S.SUSPENDED, AccessLevel.READ_ONLY),
        (S.CANCELED, AccessLevel.NONE),
    ],
)
def test_access_level_by_status(
    service: SubscriptionService, current: S, level: AccessLevel
) -> None:
    assert service.access_level(subscription(current), now=now) is level


def test_access_level_without_subscription_is_full(
    service: SubscriptionService,
) -> None:
    assert service.access_level(None, now=now) is AccessLevel.FULL


def test_expired_trial_is_read_only_even_before_the_job_runs(
    service: SubscriptionService,
) -> None:
    record = subscription(S.TRIALING, trial_ends_at=now - timedelta(seconds=1))
    assert service.access_level(record, now=now) is AccessLevel.READ_ONLY


def test_past_due_after_grace_is_read_only_even_before_the_job_runs(
    service: SubscriptionService,
) -> None:
    record = subscription(S.PAST_DUE, grace_ends_at=now - timedelta(seconds=1))
    assert service.access_level(record, now=now) is AccessLevel.READ_ONLY
    inside = subscription(S.PAST_DUE, grace_ends_at=now + timedelta(seconds=1))
    assert service.access_level(inside, now=now) is AccessLevel.FULL


@pytest.mark.parametrize(
    ("clock", "level"),
    [
        # trial ends 20/11 23:59 in Sao Paulo (UTC-3) = 21/11 02:59 UTC
        (datetime(2026, 11, 21, 2, 58, tzinfo=UTC), AccessLevel.FULL),
        # the exact instant the trial ends is already over
        (datetime(2026, 11, 21, 2, 59, tzinfo=UTC), AccessLevel.READ_ONLY),
        (datetime(2026, 11, 21, 3, 0, tzinfo=UTC), AccessLevel.READ_ONLY),
        (datetime(2026, 11, 20, 23, 58, tzinfo=ZoneInfo("America/Sao_Paulo")), AccessLevel.FULL),
        (datetime(2026, 11, 21, 0, 1, tzinfo=ZoneInfo("America/Sao_Paulo")), AccessLevel.READ_ONLY),
        # 04:00 at UTC+2 is 02:00 UTC, still before the end
        (datetime(2026, 11, 21, 4, 0, tzinfo=timezone(timedelta(hours=2))), AccessLevel.FULL),
    ],
)
def test_trial_expiry_is_compared_in_utc(
    service: SubscriptionService, clock: datetime, level: AccessLevel
) -> None:
    ends = datetime(2026, 11, 20, 23, 59, tzinfo=ZoneInfo("America/Sao_Paulo"))
    record = subscription(S.TRIALING, trial_ends_at=ends)
    assert service.access_level(record, now=clock) is level


def test_naive_datetimes_from_the_database_are_read_as_utc(
    service: SubscriptionService,
) -> None:
    record = subscription(S.TRIALING, trial_ends_at=datetime(2026, 11, 19, 11, 59))
    assert service.access_level(record, now=now) is AccessLevel.READ_ONLY
