from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
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

from app.modules.business_categories.models import BusinessCategory  # noqa: F401
from app.modules.businesses.models import Business, ServiceMode
from app.modules.subscriptions.models import Plan, Subscription, SubscriptionStatus

__all__ = ["admin", "client", "database", "password_hash"]
pytestmark = pytest.mark.real_subscription_guard
S = SubscriptionStatus


def status_of(database: Engine, business_id) -> SubscriptionStatus:
    with Session(database) as session:
        return session.scalar(
            select(Subscription.status).where(Subscription.business_id == business_id)
        )


def post(client: TestClient, admin: dict, business_id, action: str, **body):
    return client.post(
        f"{root}/{business_id}/{action}", json=body or None, headers=admin
    )


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("extend-trial", {"days": 5}),
        ("suspend", {}),
        ("reactivate", {}),
        ("cancel", {}),
    ],
)
def test_non_admin_cannot_use_any_action(
    client: TestClient, admin: dict, action: str, body: dict
) -> None:
    response = client.post(
        f"{root}/{business_a}/{action}", json=body, headers=auth_headers(owner_a)
    )
    assert response.status_code == 403


def test_extend_trial_moves_the_trial_end_forward(
    client: TestClient, database: Engine, admin: dict
) -> None:
    ends = datetime.now(UTC) + timedelta(days=3)
    with Session(database) as session:
        session.query(Subscription).filter_by(business_id=business_a).update(
            {"status": S.TRIALING, "trial_ends_at": ends}
        )
        session.commit()
    response = post(client, admin, business_a, "extend-trial", days=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "TRIALING"
    moved = datetime.fromisoformat(body["trial_ends_at"]).replace(tzinfo=UTC)
    assert abs(moved - (ends + timedelta(days=10))) < timedelta(seconds=5)


@pytest.mark.parametrize("body", [{"days": 0}, {"days": 91}, {"days": "x"}, {}])
def test_extend_trial_rejects_bad_days(
    client: TestClient, admin: dict, body: dict
) -> None:
    response = client.post(
        f"{root}/{business_a}/extend-trial", json=body, headers=admin
    )
    assert response.status_code == 422


def test_extend_trial_of_a_paying_business_is_a_conflict(
    client: TestClient, database: Engine, admin: dict
) -> None:
    assert post(client, admin, business_a, "extend-trial", days=5).status_code == 409
    assert status_of(database, business_a) == S.ACTIVE


def test_manual_suspend_blocks_writes_and_reactivate_brings_them_back(
    client: TestClient, database: Engine, admin: dict
) -> None:
    owner = auth_headers(owner_a)
    assert client.post(base_url, json=new_client, headers=owner).status_code == 201

    suspended = post(client, admin, business_a, "suspend")
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "SUSPENDED"
    assert client.post(base_url, json=new_client, headers=owner).status_code == 402
    assert client.get(base_url, headers=owner).status_code == 200

    reactivated = post(client, admin, business_a, "reactivate", days=30)
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "ACTIVE"
    end = datetime.fromisoformat(reactivated.json()["current_period_end"])
    assert abs(end.replace(tzinfo=UTC) - (datetime.now(UTC) + timedelta(days=30))) < timedelta(minutes=1)
    # The courtesy period gets a different phone: the unique constraint on clients.
    other = {**new_client, "phone": "(85) 97777-1111"}
    assert client.post(base_url, json=other, headers=owner).status_code == 201


def test_reactivate_defaults_to_thirty_days(
    client: TestClient, database: Engine, admin: dict
) -> None:
    post(client, admin, business_b, "reactivate")
    with Session(database) as session:
        record = session.scalar(
            select(Subscription).where(Subscription.business_id == business_b)
        )
    assert record.status == S.ACTIVE
    end = record.current_period_end.replace(tzinfo=UTC)
    assert abs(end - (datetime.now(UTC) + timedelta(days=30))) < timedelta(minutes=1)


def test_cancel_blocks_even_reading(
    client: TestClient, admin: dict
) -> None:
    assert post(client, admin, business_a, "cancel").json()["status"] == "CANCELED"
    assert client.get(base_url, headers=auth_headers(owner_a)).status_code == 402


def test_invalid_transition_returns_409_and_changes_nothing(
    client: TestClient, database: Engine, admin: dict
) -> None:
    post(client, admin, business_a, "cancel")
    response = post(client, admin, business_a, "suspend")
    assert response.status_code == 409
    assert status_of(database, business_a) == S.CANCELED


def test_repeating_an_action_is_harmless(
    client: TestClient, database: Engine, admin: dict
) -> None:
    assert post(client, admin, business_b, "suspend").status_code == 200
    assert status_of(database, business_b) == S.SUSPENDED


def test_business_without_subscription_is_404(
    client: TestClient, database: Engine, admin: dict
) -> None:
    with Session(database) as session:
        session.query(Subscription).filter_by(business_id=business_a).delete()
        session.commit()
    assert post(client, admin, business_a, "suspend").status_code == 404


def test_unknown_business_is_404(client: TestClient, admin: dict) -> None:
    assert post(client, admin, uuid4(), "suspend").status_code == 404


def add_business(session: Session, status: S, plan: Plan) -> None:
    business = Business(
        id=uuid4(),
        name=f"Extra {status.value}",
        category_id=1,
        whatsapp="85999999999",
        service_mode=ServiceMode.PRESENCIAL,
    )
    session.add(business)
    session.flush()
    session.add(Subscription(business_id=business.id, plan_id=plan.id, status=status))


def test_metrics_count_every_status_and_sum_each_plans_price(
    client: TestClient, database: Engine, admin: dict
) -> None:
    # The fixture already has A (ACTIVE, 4990) and B (SUSPENDED).
    with Session(database) as session:
        standard = session.scalar(select(Plan))
        pro = Plan(code="pro", name="Pro", price_cents=9900)
        session.add(pro)
        session.flush()
        add_business(session, S.ACTIVE, pro)
        add_business(session, S.ACTIVE, standard)
        add_business(session, S.PAST_DUE, standard)
        add_business(session, S.TRIALING, standard)
        add_business(session, S.TRIALING, standard)
        session.commit()
    response = client.get("/api/v1/admin/metrics", headers=admin)
    assert response.status_code == 200
    assert response.json() == {
        "counts_by_status": {
            "TRIALING": 2,
            "ACTIVE": 3,
            "PAST_DUE": 1,
            "SUSPENDED": 1,
            "CANCELED": 0,
        },
        # ACTIVE 4990 + 9900 + 4990, PAST_DUE 4990: trials and suspended pay nothing.
        "mrr_cents": 24870,
    }


def test_metrics_of_an_empty_platform_are_zero(
    client: TestClient, database: Engine, admin: dict
) -> None:
    with Session(database) as session:
        session.query(Subscription).delete()
        session.commit()
    body = client.get("/api/v1/admin/metrics", headers=admin).json()
    assert body["mrr_cents"] == 0
    assert set(body["counts_by_status"].values()) == {0}


def test_metrics_are_admin_only(client: TestClient, admin: dict) -> None:
    response = client.get("/api/v1/admin/metrics", headers=auth_headers(owner_a))
    assert response.status_code == 403
