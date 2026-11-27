from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from test_admin_access import admin, root
from test_clients import (
    auth_headers,
    base_url,
    business_a,
    business_b,
    client,
    database,
    new_client,
    owner_a,
    password_hash,
)
from test_subscription_guard import subscribe

from app.core.config import settings
from app.main import app
from app.modules.subscriptions.exceptions import GatewayError
from app.modules.subscriptions.models import (
    GatewayEvent,
    Subscription,
    SubscriptionStatus,
)
from app.modules.subscriptions.route import (
    get_optional_payment_gateway,
    get_payment_gateway,
)
from app.modules.subscriptions.service import add_month

__all__ = ["admin", "client", "database", "password_hash"]
pytestmark = pytest.mark.real_subscription_guard
S = SubscriptionStatus
TOKEN = "webhook-test-token"
HOOK = "/api/v1/webhooks/asaas"
CHECKOUT = "/api/v1/subscription/checkout"
now = datetime.now(UTC)


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_on: str | None = None

    def _go(self, name: str, *args) -> None:
        self.calls.append((name, *args))
        if self.fail_on == name:
            raise GatewayError("boom")

    def create_customer(self, *, name, email, external_id):
        self._go("create_customer", name, email, external_id)
        return "cus_1"

    def create_subscription(self, *, customer_id, price_cents, first_due, external_id):
        self._go("create_subscription", customer_id, price_cents, first_due)
        return "sub_1", "https://pay.test/i/1"

    def get_payment_url(self, subscription_id):
        self._go("get_payment_url", subscription_id)
        return "https://pay.test/i/again"

    def cancel_subscription(self, subscription_id):
        self._go("cancel_subscription", subscription_id)

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


@pytest.fixture
def gateway() -> FakeGateway:
    fake = FakeGateway()
    app.dependency_overrides[get_payment_gateway] = lambda: fake
    app.dependency_overrides[get_optional_payment_gateway] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_payment_gateway, None)
    app.dependency_overrides.pop(get_optional_payment_gateway, None)


@pytest.fixture(autouse=True)
def webhook_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ASAAS_WEBHOOK_TOKEN", SecretStr(TOKEN))


def load(database: Engine, business_id=business_a) -> Subscription:
    with Session(database) as session:
        return session.scalar(
            select(Subscription).where(Subscription.business_id == business_id)
        )


def event(kind: str, *, event_id="evt_1", subscription="sub_1", due="2026-12-01"):
    return {
        "id": event_id,
        "event": kind,
        "payment": {"id": "pay_1", "subscription": subscription, "dueDate": due},
    }


def hook(client: TestClient, body: dict, token: str | None = TOKEN):
    headers = {"asaas-access-token": token} if token is not None else {}
    return client.post(HOOK, json=body, headers=headers)


def tracked(database: Engine, status: S = S.TRIALING, **overrides) -> None:
    subscribe(database, business_a, status, gateway_subscription_id="sub_1", **overrides)


def give_gateway_id(database: Engine) -> None:
    """The admin fixture already created the subscription of business A."""
    with Session(database) as session:
        session.query(Subscription).filter_by(business_id=business_a).update(
            {"gateway_subscription_id": "sub_1"}
        )
        session.commit()


def utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


# ---------------------------------------------------------------- add_month


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (date(2026, 12, 1), date(2027, 1, 1)),
        (date(2026, 1, 31), date(2026, 2, 28)),
        (date(2028, 1, 31), date(2028, 2, 29)),
        (date(2026, 3, 31), date(2026, 4, 30)),
        (date(2026, 12, 31), date(2027, 1, 31)),
    ],
)
def test_add_month_clamps_to_the_end_of_a_short_month(start, expected) -> None:
    assert add_month(start) == expected


# ------------------------------------------------------------------ webhook


def test_webhook_without_token_is_401_and_changes_nothing(
    client: TestClient, database: Engine
) -> None:
    tracked(database)
    response = hook(client, event("PAYMENT_CONFIRMED"), token=None)
    assert response.status_code == 401
    assert load(database).status == S.TRIALING
    with Session(database) as session:
        assert session.scalar(select(GatewayEvent)) is None


def test_webhook_with_a_wrong_token_is_401(client: TestClient, database: Engine) -> None:
    tracked(database)
    assert hook(client, event("PAYMENT_CONFIRMED"), token="nope").status_code == 401
    assert load(database).status == S.TRIALING


def test_webhook_is_refused_when_the_server_has_no_token_configured(
    client: TestClient, database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ASAAS_WEBHOOK_TOKEN", SecretStr(""))
    tracked(database)
    # An empty configured token must not match an empty header.
    assert hook(client, event("PAYMENT_CONFIRMED"), token="").status_code == 503
    assert load(database).status == S.TRIALING


def test_confirmed_payment_activates_and_covers_one_more_month(
    client: TestClient, database: Engine
) -> None:
    tracked(database)
    assert hook(client, event("PAYMENT_CONFIRMED")).status_code == 200
    record = load(database)
    assert record.status == S.ACTIVE
    assert utc(record.current_period_end) == datetime(2027, 1, 1, tzinfo=UTC)


def test_received_after_confirmed_for_the_same_charge_changes_nothing(
    client: TestClient, database: Engine
) -> None:
    tracked(database)
    hook(client, event("PAYMENT_CONFIRMED", event_id="evt_1"))
    hook(client, event("PAYMENT_RECEIVED", event_id="evt_2"))
    record = load(database)
    assert record.status == S.ACTIVE
    assert utc(record.current_period_end) == datetime(2027, 1, 1, tzinfo=UTC)


def test_duplicate_event_id_is_ignored(client: TestClient, database: Engine) -> None:
    tracked(database)
    hook(client, event("PAYMENT_CONFIRMED", due="2026-12-01"))
    # Same id again, even with a different date: a replay must not add a month.
    replay = hook(client, event("PAYMENT_CONFIRMED", due="2027-06-01"))
    assert replay.status_code == 200
    assert replay.json() == {"result": "duplicate"}
    assert utc(load(database).current_period_end) == datetime(2027, 1, 1, tzinfo=UTC)


def test_overdue_after_confirmed_in_the_same_cycle_does_not_penalise(
    client: TestClient, database: Engine
) -> None:
    tracked(database)
    hook(client, event("PAYMENT_CONFIRMED", event_id="evt_1", due="2026-12-01"))
    hook(client, event("PAYMENT_OVERDUE", event_id="evt_2", due="2026-12-01"))
    record = load(database)
    assert record.status == S.ACTIVE
    assert record.grace_ends_at is None


def test_overdue_of_the_next_cycle_starts_the_grace_period(
    client: TestClient, database: Engine
) -> None:
    tracked(database)
    hook(client, event("PAYMENT_CONFIRMED", event_id="evt_1", due="2026-12-01"))
    hook(client, event("PAYMENT_OVERDUE", event_id="evt_2", due="2027-01-01"))
    record = load(database)
    assert record.status == S.PAST_DUE
    grace = utc(record.grace_ends_at)
    assert abs(grace - (datetime.now(UTC) + timedelta(days=settings.GRACE_DAYS))) < timedelta(minutes=1)


def test_overdue_of_a_business_that_never_paid_is_ignored_when_not_billable(
    client: TestClient, database: Engine
) -> None:
    tracked(database, S.SUSPENDED)
    assert hook(client, event("PAYMENT_OVERDUE")).status_code == 200
    assert load(database).status == S.SUSPENDED


def test_paying_in_grace_restores_writes(client: TestClient, database: Engine) -> None:
    tracked(database, S.PAST_DUE, grace_ends_at=now + timedelta(days=2))
    hook(client, event("PAYMENT_CONFIRMED"))
    record = load(database)
    assert record.status == S.ACTIVE and record.grace_ends_at is None
    assert client.post(base_url, json=new_client, headers=auth_headers()).status_code == 201


def test_paying_after_suspension_reactivates_the_business(
    client: TestClient, database: Engine
) -> None:
    tracked(database, S.SUSPENDED)
    assert client.post(base_url, json=new_client, headers=auth_headers()).status_code == 402
    hook(client, event("PAYMENT_RECEIVED"))
    assert client.post(base_url, json=new_client, headers=auth_headers()).status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        event("PAYMENT_CREATED"),
        event("PAYMENT_CONFIRMED", subscription="sub_unknown"),
        {"id": "evt_9", "event": "PAYMENT_CONFIRMED", "payment": {"id": "pay_9"}},
        {"id": "evt_9", "event": "SOMETHING_NEW"},
    ],
    ids=["other-event", "unknown-subscription", "one-off-payment", "no-payment"],
)
def test_unrelated_events_are_acknowledged_without_effect(
    client: TestClient, database: Engine, body: dict
) -> None:
    tracked(database)
    response = hook(client, body)
    assert response.status_code == 200
    assert load(database).status == S.TRIALING


def test_malformed_body_is_a_validation_error(client: TestClient) -> None:
    assert hook(client, {"event": "PAYMENT_CONFIRMED"}).status_code == 422


# ----------------------------------------------------------------- checkout


def test_checkout_creates_customer_and_subscription_once(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    subscribe(database, business_a, S.TRIALING, trial_ends_at=now + timedelta(days=5))
    first = client.post(CHECKOUT, headers=auth_headers())
    assert first.status_code == 200, first.text
    assert first.json() == {"payment_url": "https://pay.test/i/1"}
    assert gateway.names() == ["create_customer", "create_subscription"]
    record = load(database)
    assert (record.gateway_customer_id, record.gateway_subscription_id) == ("cus_1", "sub_1")

    second = client.post(CHECKOUT, headers=auth_headers())
    assert second.json() == {"payment_url": "https://pay.test/i/again"}
    assert gateway.names().count("create_customer") == 1
    assert gateway.names().count("create_subscription") == 1


def test_checkout_sends_the_plan_price_and_the_owners_data(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    subscribe(database, business_a, S.TRIALING, trial_ends_at=now + timedelta(days=5))
    client.post(CHECKOUT, headers=auth_headers())
    assert gateway.calls[0] == (
        "create_customer", "owner_a", "owner_a@example.com", str(business_a)
    )
    assert gateway.calls[1][2] == 4990


def test_first_charge_waits_for_the_end_of_a_running_trial(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    ends = now + timedelta(days=5)
    subscribe(database, business_a, S.TRIALING, trial_ends_at=ends)
    client.post(CHECKOUT, headers=auth_headers())
    assert gateway.calls[1][3] == ends.date()


@pytest.mark.parametrize(
    ("status", "overrides"),
    [
        (S.TRIALING, {"trial_ends_at": now - timedelta(days=3)}),
        (S.SUSPENDED, {}),
        (S.PAST_DUE, {"grace_ends_at": now + timedelta(days=1)}),
    ],
)
def test_charge_is_due_today_when_there_is_no_trial_left(
    client: TestClient, database: Engine, gateway: FakeGateway, status: S, overrides: dict
) -> None:
    subscribe(database, business_a, status, **overrides)
    client.post(CHECKOUT, headers=auth_headers())
    assert gateway.calls[1][3] == datetime.now(UTC).date()


def test_a_suspended_business_can_still_reach_checkout(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    assert client.post(CHECKOUT, headers=auth_headers()).status_code == 200


def test_checkout_failure_keeps_the_customer_so_a_retry_does_not_duplicate_it(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    subscribe(database, business_a, S.TRIALING, trial_ends_at=now + timedelta(days=5))
    gateway.fail_on = "create_subscription"
    assert client.post(CHECKOUT, headers=auth_headers()).status_code == 502
    assert load(database).gateway_customer_id == "cus_1"
    assert load(database).gateway_subscription_id is None
    gateway.fail_on = None
    assert client.post(CHECKOUT, headers=auth_headers()).status_code == 200
    assert gateway.names().count("create_customer") == 1


def test_gateway_outage_is_a_502_without_internal_details(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    gateway.fail_on = "create_customer"
    response = client.post(CHECKOUT, headers=auth_headers())
    assert response.status_code == 502
    assert response.json() == {"detail": "The payment gateway is unavailable"}


def test_an_active_business_has_nothing_to_pay(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    subscribe(database, business_a, S.ACTIVE)
    assert client.post(CHECKOUT, headers=auth_headers()).status_code == 409
    assert gateway.calls == []


def test_checkout_without_a_subscription_is_404(
    client: TestClient, gateway: FakeGateway
) -> None:
    assert client.post(CHECKOUT, headers=auth_headers()).status_code == 404


def test_checkout_needs_authentication(client: TestClient, gateway: FakeGateway) -> None:
    assert client.post(CHECKOUT).status_code == 401


def test_checkout_is_503_when_payments_are_not_configured(
    client: TestClient, database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ASAAS_API_KEY", SecretStr(""))
    subscribe(database, business_a, S.SUSPENDED)
    assert client.post(CHECKOUT, headers=auth_headers()).status_code == 503


def test_checkout_only_touches_the_callers_own_subscription(
    client: TestClient, database: Engine, gateway: FakeGateway
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    subscribe(database, business_b, S.SUSPENDED)
    client.post(CHECKOUT, headers=auth_headers(owner_a))
    assert load(database, business_a).gateway_customer_id == "cus_1"
    assert load(database, business_b).gateway_customer_id is None


# ---------------------------------------------------------- GET /subscription


def test_overview_of_a_trial(client: TestClient, database: Engine) -> None:
    subscribe(database, business_a, S.TRIALING, trial_ends_at=now + timedelta(days=4, hours=3))
    response = client.get("/api/v1/subscription", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "TRIALING"
    assert body["days_left"] == 5
    assert body["price_cents"] == 4990


def test_overview_days_left_never_goes_negative(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.PAST_DUE, grace_ends_at=now - timedelta(days=9))
    assert client.get("/api/v1/subscription", headers=auth_headers()).json()["days_left"] == 0


def test_overview_is_available_to_a_suspended_business(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    body = client.get("/api/v1/subscription", headers=auth_headers()).json()
    assert body["status"] == "SUSPENDED" and body["days_left"] is None


def test_overview_without_a_subscription_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/subscription", headers=auth_headers()).status_code == 404


# ------------------------------------------------- admin cancel and the gateway


def test_admin_cancel_also_stops_the_charges_at_the_gateway(
    client: TestClient, database: Engine, admin: dict, gateway: FakeGateway
) -> None:
    give_gateway_id(database)
    response = client.post(f"{root}/{business_a}/cancel", headers=admin)
    assert response.status_code == 200
    assert gateway.calls == [("cancel_subscription", "sub_1")]
    record = load(database)
    assert record.status == S.CANCELED and record.gateway_subscription_id is None


def test_failed_gateway_cancel_is_reported_and_can_be_retried(
    client: TestClient, database: Engine, admin: dict, gateway: FakeGateway
) -> None:
    give_gateway_id(database)
    gateway.fail_on = "cancel_subscription"
    assert client.post(f"{root}/{business_a}/cancel", headers=admin).status_code == 502
    record = load(database)
    assert record.status == S.CANCELED and record.gateway_subscription_id == "sub_1"
    gateway.fail_on = None
    assert client.post(f"{root}/{business_a}/cancel", headers=admin).status_code == 200
    assert load(database).gateway_subscription_id is None


def test_admin_cancel_without_a_gateway_subscription_never_calls_the_gateway(
    client: TestClient, database: Engine, admin: dict, gateway: FakeGateway
) -> None:
    assert client.post(f"{root}/{business_a}/cancel", headers=admin).status_code == 200
    assert gateway.calls == []
