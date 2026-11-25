import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session
from test_clients import database, password_hash

from app.core.security import verify_password
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business
from app.modules.users.models import User
from scripts.seed_test_business import (
    TEST_BUSINESS_ID,
    SeedError,
    seed_test_business,
)

__all__ = ["database", "password_hash"]
EMAIL = "dono.testes@example.com"


@pytest.fixture
def engine(database: Engine) -> Engine:
    with Session(database) as session:
        session.add(BusinessCategory(name="Barbearia"))
        session.commit()
    return database


def user_count(engine: Engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(User))


def test_creates_business_with_fixed_id_once(engine: Engine) -> None:
    first = seed_test_business(engine, app_env="development")
    second = seed_test_business(engine, app_env="development")
    assert first["business_created"] is True
    assert second["business_created"] is False
    assert first["business_id"] == str(TEST_BUSINESS_ID)
    assert first["owner_created"] is False
    with Session(engine) as session:
        business = session.get(Business, TEST_BUSINESS_ID)
        assert business is not None and "[SEED]" in business.name


def test_creates_owner_login_once_without_storing_plain_password(
    engine: Engine,
) -> None:
    users_before = user_count(engine)
    result = seed_test_business(
        engine,
        app_env="development",
        owner_email=" Dono.Testes@Example.com ",
        owner_password="senha-de-teste",
    )
    again = seed_test_business(
        engine,
        app_env="development",
        owner_email=EMAIL,
        owner_password="outra-senha-123",
    )
    assert result["owner_created"] is True and again["owner_created"] is False
    assert user_count(engine) == users_before + 1
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user.business_id == TEST_BUSINESS_ID
        assert user.password_hash != "senha-de-teste"
        # Re-running never resets a password the person may have changed.
        assert verify_password("senha-de-teste", user.password_hash)


def test_refuses_email_of_another_account(engine: Engine) -> None:
    with Session(engine) as session:
        taken = session.scalar(select(User.email).where(User.business_id.is_not(None)))
    with pytest.raises(SeedError):
        seed_test_business(
            engine,
            app_env="development",
            owner_email=taken,
            owner_password="senha-de-teste",
        )
    with Session(engine) as session:
        assert session.get(Business, TEST_BUSINESS_ID) is None


@pytest.mark.parametrize(
    "credentials",
    [
        {"owner_email": EMAIL},
        {"owner_password": "senha-de-teste"},
    ],
)
def test_requires_email_and_password_together(engine: Engine, credentials) -> None:
    with pytest.raises(SeedError):
        seed_test_business(engine, app_env="development", **credentials)


def test_is_blocked_in_production(engine: Engine) -> None:
    with pytest.raises(SeedError):
        seed_test_business(engine, app_env="production")
    with Session(engine) as session:
        assert session.get(Business, TEST_BUSINESS_ID) is None


def test_requires_migrated_business_categories(engine: Engine) -> None:
    with Session(engine) as session:
        session.execute(
            delete(BusinessCategory).where(BusinessCategory.name == "Barbearia")
        )
        session.commit()
    with pytest.raises(SeedError):
        seed_test_business(engine, app_env="development")
