"""Create the fictitious test business, with a fixed id, and optionally its owner login."""

import argparse
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.schemas import BusinessCreate
from app.modules.subscriptions.models import Subscription, SubscriptionStatus
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate

# Fixed so seeds, Docker and manual tests can always reach the same business.
TEST_BUSINESS_ID = UUID("00000000-0000-4000-8000-000000000001")
TEST_BUSINESS_CATEGORY = "Barbearia"
# The demo business must never fall into read-only because a trial ended.
DEMO_PAID_UNTIL = datetime(2099, 12, 31, tzinfo=UTC)


class SeedError(Exception):
    pass


def guard_environment(app_env: str) -> None:
    if app_env not in ("development", "test"):
        raise SeedError("Seed bloqueado fora de development/test.")


def seed_test_business(
    engine: Engine,
    *,
    app_env: str,
    owner_email: str | None = None,
    owner_password: str | None = None,
) -> dict[str, Any]:
    guard_environment(app_env)
    if bool(owner_email) != bool(owner_password):
        raise SeedError("Informe SEED_USER_EMAIL e SEED_USER_PASSWORD juntos.")
    owner = (
        UserCreate(name="Dono de Testes", email=owner_email, password=owner_password)
        if owner_email and owner_password
        else None
    )
    result: dict[str, Any] = {
        "business_id": str(TEST_BUSINESS_ID),
        "business_created": False,
        "owner_created": False,
    }
    with Session(engine) as session, session.begin():
        if session.get(Business, TEST_BUSINESS_ID) is None:
            category_id = session.scalar(
                select(BusinessCategory.id).where(
                    BusinessCategory.name == TEST_BUSINESS_CATEGORY
                )
            )
            if category_id is None:
                raise SeedError(
                    "Categoria de empresa ausente; aplique as migrations antes do seed."
                )
            data = BusinessCreate(
                name="Barbearia Fictícia [SEED]",
                category_id=category_id,
                whatsapp="00000000000",
                service_mode=ServiceMode.PRESENCIAL,
                description="Empresa fictícia para testes locais.",
                city="Cidade Fictícia",
            )
            session.add(Business(id=TEST_BUSINESS_ID, **data.model_dump()))
            session.flush()
            result["business_created"] = True
        subscription = session.scalar(
            select(Subscription).where(Subscription.business_id == TEST_BUSINESS_ID)
        )
        if subscription is not None:
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.current_period_end = DEMO_PAID_UNTIL
            subscription.grace_ends_at = None
            subscription.canceled_at = None
        if owner is None:
            return result
        email = str(owner.email).strip().lower()
        result["owner_email"] = email
        linked = session.scalar(
            select(User).where(User.business_id == TEST_BUSINESS_ID)
        )
        existing = session.scalar(select(User).where(User.email == email))
        if existing is not None:
            # Existing accounts are never changed: passwords stay as the person set them.
            if existing.business_id != TEST_BUSINESS_ID:
                raise SeedError(
                    "O e-mail de SEED_USER_EMAIL já pertence a outra conta."
                )
            return result
        if linked is not None:
            raise SeedError("A empresa de testes já tem outro usuário vinculado.")
        # Imported here: security loads the settings, which scripts.seed must not need.
        from app.core.security import hash_password

        session.add(
            User(
                name=owner.name,
                email=email,
                password_hash=hash_password(owner.password),
                business_id=TEST_BUSINESS_ID,
            )
        )
        result["owner_created"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cria a empresa fictícia de testes e, opcionalmente, o login do dono."
    )
    parser.parse_args(argv)
    from app.core.config import settings

    try:
        guard_environment(settings.APP_ENV)
        from app.db.session import engine

        result = seed_test_business(
            engine,
            app_env=settings.APP_ENV,
            owner_email=settings.SEED_USER_EMAIL or None,
            owner_password=settings.SEED_USER_PASSWORD.get_secret_value() or None,
        )
    except SeedError as exc:
        parser.exit(2, f"Seed recusado: {exc}\n")
    except ValueError:
        parser.exit(
            2,
            "Seed recusado: SEED_USER_EMAIL inválido ou SEED_USER_PASSWORD com menos de 8 caracteres.\n",
        )
    except SQLAlchemyError:
        parser.exit(
            1,
            "Falha de banco. Nada foi gravado; confira conexão, migrations e permissões.\n",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
