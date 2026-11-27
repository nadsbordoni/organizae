from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from test_clients import (
    auth_headers,
    business_a,
    business_b,
    client,
    database,
    owner_a,
    password_hash,
)

from app.modules.auth.schemas import LoginRequest
from app.modules.subscriptions.models import Plan, Subscription, SubscriptionStatus
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate

__all__ = ["client", "database", "password_hash"]
S = SubscriptionStatus
admin_id = uuid4()
root = "/api/v1/admin/businesses"


@pytest.fixture
def admin(database: Engine, password_hash: str) -> dict[str, str]:
    with Session(database) as session:
        plan = Plan(code="standard", name="Organizaê", price_cents=4990)
        session.add(plan)
        session.add(
            User(
                id=admin_id,
                name="Platform admin",
                email="admin@organizae.test",
                password_hash=password_hash,
                is_active=True,
                is_platform_admin=True,
            )
        )
        session.flush()
        session.add_all(
            [
                Subscription(business_id=business_a, plan_id=plan.id, status=S.ACTIVE),
                Subscription(business_id=business_b, plan_id=plan.id, status=S.SUSPENDED),
            ]
        )
        session.commit()
    return auth_headers(admin_id)


ADMIN_ROUTES = [("get", root), ("get", f"{root}/{business_a}")]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_non_admin_gets_403_on_every_admin_route(
    client: TestClient, admin: dict, method: str, path: str
) -> None:
    response = getattr(client, method)(path, headers=auth_headers(owner_a))
    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_unauthenticated_gets_401(
    client: TestClient, admin: dict, method: str, path: str
) -> None:
    assert getattr(client, method)(path).status_code == 401


def test_admin_lists_businesses_with_subscription_status(
    client: TestClient, admin: dict
) -> None:
    response = client.get(root, headers=admin)
    assert response.status_code == 200
    rows = {row["business_id"]: row for row in response.json()}
    assert set(rows) == {str(business_a), str(business_b)}
    assert rows[str(business_a)]["status"] == "ACTIVE"
    assert rows[str(business_b)]["status"] == "SUSPENDED"
    assert rows[str(business_a)]["owner_email"] == "owner_a@example.com"
    assert set(rows[str(business_a)]) == {
        "business_id",
        "name",
        "owner_email",
        "status",
        "trial_ends_at",
        "current_period_end",
    }


def test_list_filters_by_status(client: TestClient, admin: dict) -> None:
    rows = client.get(root, params={"status": "SUSPENDED"}, headers=admin).json()
    assert [row["business_id"] for row in rows] == [str(business_b)]


def test_list_searches_by_business_name_or_owner_email(
    client: TestClient, admin: dict
) -> None:
    rows = client.get(root, params={"q": "OWNER_B"}, headers=admin).json()
    assert [row["business_id"] for row in rows] == [str(business_b)]
    assert client.get(root, params={"q": "nobody"}, headers=admin).json() == []


def test_list_rejects_an_unknown_status(client: TestClient, admin: dict) -> None:
    assert client.get(root, params={"status": "FREE"}, headers=admin).status_code == 422


def test_list_paginates_in_a_stable_order(client: TestClient, admin: dict) -> None:
    everything = [row["business_id"] for row in client.get(root, headers=admin).json()]
    first = client.get(root, params={"limit": 1}, headers=admin).json()
    second = client.get(root, params={"limit": 1, "offset": 1}, headers=admin).json()
    assert [first[0]["business_id"], second[0]["business_id"]] == everything


@pytest.mark.parametrize(
    "params", [{"limit": 101}, {"limit": 0}, {"offset": -1}], ids=str
)
def test_list_pagination_is_bounded(
    client: TestClient, admin: dict, params: dict
) -> None:
    assert client.get(root, params=params, headers=admin).status_code == 422


def test_business_without_a_subscription_is_listed_with_no_status(
    client: TestClient, database: Engine, admin: dict
) -> None:
    with Session(database) as session:
        session.query(Subscription).filter_by(business_id=business_b).delete()
        session.commit()
    rows = {row["business_id"]: row for row in client.get(root, headers=admin).json()}
    assert rows[str(business_b)]["status"] is None


def test_admin_reads_one_business_with_plan_and_dates(
    client: TestClient, admin: dict
) -> None:
    response = client.get(f"{root}/{business_a}", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["business_id"] == str(business_a)
    assert body["status"] == "ACTIVE"
    assert body["plan_code"] == "standard"
    assert body["price_cents"] == 4990
    assert {"grace_ends_at", "canceled_at", "owner_name"} <= set(body)


def test_unknown_business_is_404(client: TestClient, admin: dict) -> None:
    assert client.get(f"{root}/{uuid4()}", headers=admin).status_code == 404


def test_admin_routes_work_even_though_the_admin_has_no_business(
    client: TestClient, admin: dict
) -> None:
    assert client.get(root, headers=admin).status_code == 200


def test_inactive_admin_is_refused(
    client: TestClient, database: Engine, admin: dict
) -> None:
    with Session(database) as session:
        session.get(User, admin_id).is_active = False
        session.commit()
    assert client.get(root, headers=admin).status_code == 401


def test_new_users_are_not_admins_by_default(
    client: TestClient, database: Engine, admin: dict
) -> None:
    with Session(database) as session:
        assert session.get(User, owner_a).is_platform_admin is False


@pytest.mark.parametrize("schema", [UserCreate, UserUpdate, LoginRequest])
def test_no_public_schema_accepts_the_admin_flag(schema: type) -> None:
    assert "is_platform_admin" not in schema.model_fields
    assert schema.model_config.get("extra") == "forbid"


def test_signup_cannot_smuggle_the_admin_flag(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={
            "name": "Mallory",
            "email": "mallory@example.com",
            "password": "a-long-password",
            "is_platform_admin": True,
        },
    )
    assert response.status_code == 422


def test_platform_admin_migration_only_adds_a_safe_default_column() -> None:
    from io import StringIO
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    revision = ScriptDirectory.from_config(config).get_revision("f3a9d6e51b70")
    assert revision.down_revision == "e1b7c4d92a58"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()
    assert "ALTER TABLE users ADD COLUMN is_platform_admin BOOLEAN DEFAULT false NOT NULL" in sql
    assert "DROP" not in sql
