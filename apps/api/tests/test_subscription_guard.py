from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from test_clients import (
    auth_headers,
    base_url,
    business_a,
    client,
    client_a,
    database,
    new_client,
    owner_b,
    password_hash,
    unassigned_user,
)

from app.modules.subscriptions.models import Plan, Subscription, SubscriptionStatus

__all__ = ["client", "database", "password_hash"]
pytestmark = pytest.mark.real_subscription_guard
S = SubscriptionStatus
now = datetime.now(UTC)
SUSPENDED = {"detail": "SUBSCRIPTION_SUSPENDED"}


def subscribe(database: Engine, business_id, status: S, **overrides) -> None:
    with Session(database) as session:
        plan = session.scalar(select(Plan)) or Plan(
            code="standard", name="Organizaê", price_cents=4990
        )
        session.add(plan)
        session.flush()
        session.add(
            Subscription(
                business_id=business_id, plan_id=plan.id, status=status, **overrides
            )
        )
        session.commit()


def test_business_without_a_subscription_row_is_not_blocked(
    client: TestClient,
) -> None:
    assert client.post(base_url, json=new_client, headers=auth_headers()).status_code == 201


@pytest.mark.parametrize(
    ("status", "overrides"),
    [
        (S.ACTIVE, {}),
        (S.TRIALING, {"trial_ends_at": now + timedelta(days=3)}),
        (S.PAST_DUE, {"grace_ends_at": now + timedelta(days=3)}),
    ],
)
def test_paying_trial_and_grace_businesses_can_write(
    client: TestClient, database: Engine, status: S, overrides: dict
) -> None:
    subscribe(database, business_a, status, **overrides)
    response = client.post(base_url, json=new_client, headers=auth_headers())
    assert response.status_code == 201


def test_suspended_business_can_read(client: TestClient, database: Engine) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    response = client.get(base_url, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", base_url),
        ("patch", f"{base_url}/{client_a}"),
        ("delete", f"/api/v1/businesses/{business_a}"),
    ],
)
def test_suspended_business_cannot_write_returns_402(
    client: TestClient, database: Engine, method: str, path: str
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    body = {} if method == "delete" else {"json": {"name": "Changed"}}
    response = getattr(client, method)(path, headers=auth_headers(), **body)
    assert response.status_code == 402
    assert response.json() == SUSPENDED


def test_suspended_write_changes_nothing(client: TestClient, database: Engine) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    before = client.get(base_url, headers=auth_headers()).json()
    client.post(base_url, json=new_client, headers=auth_headers())
    assert client.get(base_url, headers=auth_headers()).json() == before


def test_expired_trial_blocks_writes_without_waiting_for_the_job(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.TRIALING, trial_ends_at=now - timedelta(minutes=1))
    assert client.post(base_url, json=new_client, headers=auth_headers()).status_code == 402
    assert client.get(base_url, headers=auth_headers()).status_code == 200


def test_expired_grace_blocks_writes_without_waiting_for_the_job(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.PAST_DUE, grace_ends_at=now - timedelta(minutes=1))
    assert client.post(base_url, json=new_client, headers=auth_headers()).status_code == 402


def test_canceled_business_is_blocked_even_for_reading(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.CANCELED)
    response = client.get(base_url, headers=auth_headers())
    assert response.status_code == 402
    assert response.json() == {"detail": "SUBSCRIPTION_CANCELED"}


def test_one_suspended_business_does_not_block_another(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    response = client.post(base_url, json=new_client, headers=auth_headers(owner_b))
    assert response.status_code == 201


def test_unauthenticated_requests_keep_returning_401(client: TestClient) -> None:
    assert client.post(base_url, json=new_client).status_code == 401


def test_public_booking_refused_when_suspended(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    url = f"/api/v1/public/businesses/{business_a}/appointments"
    response = client.post(url, json={})
    assert response.status_code == 402
    assert response.json() == SUSPENDED


def test_public_booking_still_open_when_active(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.ACTIVE)
    url = f"/api/v1/public/businesses/{business_a}/appointments"
    # Past the guard, the empty body is rejected by validation instead.
    assert client.post(url, json={}).status_code == 422


def test_public_pages_stay_readable_when_suspended(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.SUSPENDED)
    url = f"/api/v1/public/businesses/{business_a}/services"
    assert client.get(url).status_code == 200


def test_public_booking_for_an_unknown_business_is_not_a_payment_error(
    client: TestClient,
) -> None:
    url = f"/api/v1/public/businesses/{uuid4()}/appointments"
    assert client.post(url, json={}).status_code == 422


def test_auth_and_signup_are_never_blocked(
    client: TestClient, database: Engine
) -> None:
    subscribe(database, business_a, S.CANCELED)
    assert client.post("/api/v1/auth/login", json={}).status_code != 402
    assert client.post("/api/v1/users", json={}).status_code != 402


def test_new_business_starts_a_trial(client: TestClient, database: Engine) -> None:
    with Session(database) as session:
        session.add(Plan(code="standard", name="Organizaê", price_cents=4990))
        session.commit()
    response = client.post(
        "/api/v1/businesses",
        json={
            "name": "Novo Studio",
            "category_id": 1,
            "whatsapp": "85999999999",
            "service_mode": "HIBRIDO",
        },
        headers=auth_headers(unassigned_user),
    )
    assert response.status_code == 201, response.text
    with Session(database) as session:
        record = session.scalar(
            select(Subscription).where(
                Subscription.business_id == UUID(response.json()["id"])
            )
        )
    assert record is not None
    assert record.status == S.TRIALING
    ends = record.trial_ends_at.replace(tzinfo=UTC)
    assert abs(ends - (datetime.now(UTC) + timedelta(days=15))) < timedelta(minutes=1)


def test_deleting_a_business_removes_its_subscription(
    client: TestClient, database: Engine
) -> None:
    with Session(database) as session:
        session.add(Plan(code="standard", name="Organizaê", price_cents=4990))
        session.commit()
    headers = auth_headers(unassigned_user)
    created = client.post(
        "/api/v1/businesses",
        json={
            "name": "Novo Studio",
            "category_id": 1,
            "whatsapp": "85999999999",
            "service_mode": "HIBRIDO",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    assert client.delete(f"/api/v1/businesses/{identifier}", headers=headers).status_code == 204
    with Session(database) as session:
        assert session.scalar(select(Subscription)) is None
