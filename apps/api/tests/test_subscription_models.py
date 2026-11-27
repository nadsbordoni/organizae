from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.appointments.models import Appointment, BusinessHour  # noqa: F401
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.models import Professional  # noqa: F401
from app.modules.services.models import Service  # noqa: F401
from app.modules.subscriptions.models import (
    GatewayEvent,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.modules.subscriptions.repository import SubscriptionRepository
from app.modules.users.models import User  # noqa: F401

business_id = uuid4()


@pytest.fixture
def database() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    # Only this disposable test database is created from ORM metadata.
    for table in Base.metadata.sorted_tables:
        table.create(engine)
    with Session(engine) as session:
        session.add(BusinessCategory(id=1, name="Beauty"))
        session.flush()
        session.add(
            Business(
                id=business_id,
                name="Studio Bela",
                category_id=1,
                whatsapp="85999999999",
                service_mode=ServiceMode.PRESENCIAL,
            )
        )
        session.add(Plan(code="standard", name="Organizaê", price_cents=4990))
        session.commit()
    yield engine
    engine.dispose()


def test_business_has_at_most_one_subscription(database: Engine) -> None:
    with Session(database) as session:
        plan = SubscriptionRepository(session).get_default_plan()
        repository = SubscriptionRepository(session)
        repository.add(
            Subscription(
                business_id=business_id,
                plan_id=plan.id,
                status=SubscriptionStatus.TRIALING,
            )
        )
        with pytest.raises(IntegrityError):
            repository.add(
                Subscription(
                    business_id=business_id,
                    plan_id=plan.id,
                    status=SubscriptionStatus.ACTIVE,
                )
            )


def test_price_must_not_be_negative(database: Engine) -> None:
    with Session(database) as session:
        session.add(Plan(code="broken", name="Broken", price_cents=-1))
        with pytest.raises(IntegrityError):
            session.flush()


def test_repository_finds_the_subscription_by_business(database: Engine) -> None:
    with Session(database) as session:
        repository = SubscriptionRepository(session)
        assert repository.get_by_business_id(business_id) is None
        plan = repository.get_default_plan()
        assert plan.price_cents == 4990
        created = repository.add(
            Subscription(
                business_id=business_id,
                plan_id=plan.id,
                status=SubscriptionStatus.TRIALING,
            )
        )
        assert repository.get_by_business_id(business_id) is created
        assert repository.get_by_business_id(uuid4()) is None


def test_gateway_event_id_is_unique(database: Engine) -> None:
    with Session(database) as session:
        session.add(GatewayEvent(event_id="evt_1"))
        session.flush()
        session.add(GatewayEvent(event_id="evt_1"))
        with pytest.raises(IntegrityError):
            session.flush()


def render(revision_id: str, direction: str) -> str:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(revision_id)
    assert revision.revision in {
        item.revision for item in script.iterate_revisions("head", "base")
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(revision.module, direction)()
    return output.getvalue()


def test_subscriptions_migration_creates_tables_and_backfills_a_trial() -> None:
    sql = render("e1b7c4d92a58", "upgrade")
    assert "CREATE TABLE plans" in sql
    assert "CREATE TABLE subscriptions" in sql
    assert "CREATE TABLE gateway_events" in sql
    assert "price_cents INTEGER NOT NULL" in sql
    assert "CONSTRAINT uq_subscriptions_business_id UNIQUE (business_id)" in sql
    assert "ck_plans_price_cents" in sql
    assert "ck_subscriptions_status" in sql
    assert "INSERT INTO plans" in sql and "4990" in sql
    # Existing businesses get a trial instead of being blocked.
    assert "INSERT INTO subscriptions" in sql
    assert "'TRIALING'" in sql and "interval '15 days'" in sql
    assert "DROP" not in sql


def test_subscriptions_migration_sits_on_top_of_the_history() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    revision = ScriptDirectory.from_config(config).get_revision("e1b7c4d92a58")
    assert revision.down_revision == "9b72e4f1a603"


def test_subscriptions_migration_downgrade_only_removes_its_tables() -> None:
    sql = render("e1b7c4d92a58", "downgrade")
    assert "DROP TABLE subscriptions" in sql
    assert "DROP TABLE gateway_events" in sql
    assert "DROP TABLE plans" in sql
    assert "businesses" not in sql.replace("subscriptions", "")
