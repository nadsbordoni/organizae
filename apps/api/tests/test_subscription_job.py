from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from test_clients import client, database, password_hash

from app.modules.businesses.models import Business, ServiceMode
from app.modules.subscriptions.models import Plan, Subscription, SubscriptionStatus
from app.modules.subscriptions.repository import SubscriptionRepository
from app.modules.subscriptions.service import AccessLevel, SubscriptionService

__all__ = ["client", "database", "password_hash"]
S = SubscriptionStatus
now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
day = timedelta(days=1)


@pytest.fixture
def plan(database: Engine) -> UUID:
    with Session(database) as session:
        record = Plan(code="standard", name="Organizaê", price_cents=4990)
        session.add(record)
        session.commit()
        return record.id


def make(database: Engine, plan_id: UUID, status: S, **overrides) -> UUID:
    business_id = uuid4()
    with Session(database) as session:
        session.add(
            Business(
                id=business_id,
                name=f"Studio {status.value}",
                category_id=1,
                whatsapp="85999999999",
                service_mode=ServiceMode.PRESENCIAL,
            )
        )
        session.flush()
        session.add(
            Subscription(
                business_id=business_id, plan_id=plan_id, status=status, **overrides
            )
        )
        session.commit()
    return business_id


def load(database: Engine, business_id: UUID) -> Subscription:
    with Session(database) as session:
        return session.scalar(
            select(Subscription).where(Subscription.business_id == business_id)
        )


def run(database: Engine, **kwargs) -> dict[str, int]:
    with Session(database) as session:
        return SubscriptionService(session).process_due(now=now, **kwargs)


def utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def test_expired_trial_is_suspended(database: Engine, plan: UUID) -> None:
    expired = make(database, plan, S.TRIALING, trial_ends_at=now - timedelta(minutes=1))
    assert run(database)["trial_suspended"] == 1
    assert load(database, expired).status == S.SUSPENDED


def test_trial_still_running_is_untouched(database: Engine, plan: UUID) -> None:
    running = make(database, plan, S.TRIALING, trial_ends_at=now + day)
    assert run(database) == {
        "trial_suspended": 0,
        "period_lapsed": 0,
        "grace_suspended": 0,
    }
    assert load(database, running).status == S.TRIALING


def test_past_due_inside_grace_is_untouched(database: Engine, plan: UUID) -> None:
    waiting = make(database, plan, S.PAST_DUE, grace_ends_at=now + day)
    run(database)
    assert load(database, waiting).status == S.PAST_DUE


def test_past_due_after_grace_is_suspended(database: Engine, plan: UUID) -> None:
    late = make(database, plan, S.PAST_DUE, grace_ends_at=now - timedelta(seconds=1))
    assert run(database)["grace_suspended"] == 1
    assert load(database, late).status == S.SUSPENDED


def test_active_with_a_lapsed_period_enters_grace_counted_from_the_period_end(
    database: Engine, plan: UUID
) -> None:
    lapsed = make(database, plan, S.ACTIVE, current_period_end=now - day)
    assert run(database)["period_lapsed"] == 1
    record = load(database, lapsed)
    assert record.status == S.PAST_DUE
    # Grace starts when the period ended, not when the job happened to run.
    assert utc(record.grace_ends_at) == now - day + timedelta(days=5)


def test_active_whose_period_and_grace_both_ended_is_suspended_in_one_run(
    database: Engine, plan: UUID
) -> None:
    long_gone = make(database, plan, S.ACTIVE, current_period_end=now - timedelta(days=30))
    counts = run(database)
    assert load(database, long_gone).status == S.SUSPENDED
    assert counts["period_lapsed"] == 1 and counts["grace_suspended"] == 1


@pytest.mark.parametrize(
    "overrides",
    [{"current_period_end": None}, {"current_period_end": now + day}],
    ids=["no-period", "future-period"],
)
def test_active_with_time_left_is_untouched(
    database: Engine, plan: UUID, overrides: dict
) -> None:
    paying = make(database, plan, S.ACTIVE, **overrides)
    run(database)
    assert load(database, paying).status == S.ACTIVE


@pytest.mark.parametrize("status", [S.SUSPENDED, S.CANCELED])
def test_suspended_and_canceled_are_left_alone(
    database: Engine, plan: UUID, status: S
) -> None:
    done = make(
        database,
        plan,
        status,
        trial_ends_at=now - day,
        grace_ends_at=now - day,
        current_period_end=now - day,
    )
    assert sum(run(database).values()) == 0
    assert load(database, done).status == status


def test_running_twice_is_idempotent(database: Engine, plan: UUID) -> None:
    make(database, plan, S.TRIALING, trial_ends_at=now - day)
    make(database, plan, S.PAST_DUE, grace_ends_at=now - day)
    make(database, plan, S.ACTIVE, current_period_end=now - day)
    assert sum(run(database).values()) == 3
    assert sum(run(database).values()) == 0


def test_a_run_larger_than_the_batch_still_handles_everything(
    database: Engine, plan: UUID
) -> None:
    ids = [
        make(database, plan, S.TRIALING, trial_ends_at=now - day) for _ in range(5)
    ]
    assert run(database, batch_size=2)["trial_suspended"] == 5
    assert {load(database, item).status for item in ids} == {S.SUSPENDED}


def test_the_batch_size_must_be_positive(database: Engine) -> None:
    with Session(database) as session, pytest.raises(ValueError, match="batch_size"):
        SubscriptionService(session).process_due(now=now, batch_size=0)


def test_a_failure_rolls_back_the_batch_in_progress(
    database: Engine, plan: UUID
) -> None:
    doomed = make(database, plan, S.TRIALING, trial_ends_at=now - day)
    with Session(database) as session, pytest.raises(RuntimeError):
        service = SubscriptionService(session)
        service.repository = Mock(wraps=SubscriptionRepository(session))
        service.repository.list_period_lapsed.side_effect = RuntimeError("boom")
        service.process_due(now=now)
    # The trial stage had already committed its own batch before the failure.
    assert load(database, doomed).status == S.SUSPENDED


# access_level closes the same gap for requests that arrive before the job runs.


def sub(status: S, **overrides) -> Subscription:
    return Subscription(id=uuid4(), business_id=uuid4(), plan_id=uuid4(), status=status, **overrides)


@pytest.fixture
def service() -> SubscriptionService:
    return SubscriptionService(Mock())


def test_active_whose_period_and_grace_ended_is_read_only(
    service: SubscriptionService,
) -> None:
    record = sub(S.ACTIVE, current_period_end=now - timedelta(days=5, seconds=1))
    assert service.access_level(record, now=now) is AccessLevel.READ_ONLY


@pytest.mark.parametrize(
    "ended",
    [now + day, now - timedelta(days=4), now - timedelta(days=5) + timedelta(seconds=1)],
    ids=["future", "inside-grace", "last-second-of-grace"],
)
def test_active_inside_its_period_or_grace_keeps_full_access(
    service: SubscriptionService, ended: datetime
) -> None:
    assert (
        service.access_level(sub(S.ACTIVE, current_period_end=ended), now=now)
        is AccessLevel.FULL
    )


def test_active_without_a_period_keeps_full_access(
    service: SubscriptionService,
) -> None:
    assert service.access_level(sub(S.ACTIVE), now=now) is AccessLevel.FULL
