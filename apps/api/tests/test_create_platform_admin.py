import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from test_clients import client, database, owner_a, password_hash

from app.modules.users.models import User
from scripts.create_platform_admin import promote

__all__ = ["client", "database", "password_hash"]


def test_promote_turns_an_existing_user_into_an_admin(database: Engine) -> None:
    with Session(database) as session:
        user = promote(session, "owner_a@example.com")
        session.commit()
        assert user.id == owner_a
    with Session(database) as session:
        assert session.get(User, owner_a).is_platform_admin is True


def test_promote_ignores_case_and_surrounding_spaces(database: Engine) -> None:
    with Session(database) as session:
        assert promote(session, "  Owner_A@Example.COM ").id == owner_a


def test_promote_is_idempotent(database: Engine) -> None:
    with Session(database) as session:
        promote(session, "owner_a@example.com")
        assert promote(session, "owner_a@example.com").is_platform_admin is True


def test_promote_refuses_an_unknown_email_and_creates_nobody(
    database: Engine,
) -> None:
    with Session(database) as session:
        before = session.query(User).count()
        with pytest.raises(LookupError, match="nobody@example.com"):
            promote(session, "nobody@example.com")
        assert session.query(User).count() == before


def test_promote_refuses_an_inactive_user(database: Engine) -> None:
    with Session(database) as session:
        with pytest.raises(ValueError, match="inactive"):
            promote(session, "inactive@example.com")
        assert session.query(User).filter_by(is_platform_admin=True).count() == 0
