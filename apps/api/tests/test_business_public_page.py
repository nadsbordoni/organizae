"""Funcionalidade: Página comercial.

Como empreendedor, quero criar uma página pública para meu negócio,
para divulgar meus serviços e facilitar o contato com clientes.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.main import app
    from app.modules.businesses.router import get_business_service

from app.modules.auth.dependencies import get_current_user
from app.modules.businesses.exceptions import (
    BusinessNotFoundError,
    BusinessNotPublishableError,
)
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.repository import BusinessRepository
from app.modules.businesses.schemas import BusinessCreate, BusinessUpdate
from app.modules.businesses.service import BusinessService, slugify
from app.modules.services.models import Service
from app.modules.users.models import User

business_id = UUID("8ccacb20-1d36-44a7-9d32-08ac5f6bf15e")


def make_business(**overrides: object) -> Business:
    fields = {
        "id": business_id,
        "name": "Studio Aurora",
        "category_id": 1,
        "whatsapp": "11988882018",
        "service_mode": ServiceMode.PRESENCIAL,
        "is_published": False,
    }
    return Business(**{**fields, **overrides})


def make_service(name: str, price: str, minutes: int, **overrides: object) -> Service:
    fields = {
        "id": uuid4(),
        "business_id": business_id,
        "name": name,
        "price": Decimal(price),
        "duration_minutes": minutes,
        "is_active": True,
    }
    return Service(**{**fields, **overrides})


class InMemoryBusinessRepository:
    """Keeps the data in memory so the scenario runs without PostgreSQL."""

    def __init__(self, businesses: list[Business]) -> None:
        self.businesses = {business.id: business for business in businesses}
        self.services: list[Service] = []

    def get_by_id(self, business_id: UUID) -> Business | None:
        return self.businesses.get(business_id)

    get_by_id_for_update = get_by_id

    def update(self, business: Business, business_data: BusinessUpdate) -> Business:
        for field_name, value in business_data.model_dump(exclude_unset=True).items():
            setattr(business, field_name, value)
        return business

    def slug_exists(self, slug: str) -> bool:
        return any(business.slug == slug for business in self.businesses.values())

    def get_published_by_slug(self, slug: str) -> Business | None:
        return next(
            (
                business
                for business in self.businesses.values()
                if business.slug == slug and business.is_published
            ),
            None,
        )

    def list_active_services(self, business_id: UUID) -> list[Service]:
        return sorted(
            (
                service
                for service in self.services
                if service.business_id == business_id and service.is_active
            ),
            key=lambda service: service.name,
        )

    def has_active_services(self, business_id: UUID) -> bool:
        return bool(self.list_active_services(business_id))

    def publish(
        self, business: Business, *, slug: str, published_at: datetime
    ) -> Business:
        business.slug = slug
        business.is_published = True
        business.published_at = published_at
        return business


@pytest.fixture
def repository() -> InMemoryBusinessRepository:
    return InMemoryBusinessRepository([make_business()])


@pytest.fixture
def service(repository: InMemoryBusinessRepository) -> BusinessService:
    service = BusinessService(Mock(spec=Session))
    service.repository = repository
    return service


@pytest.fixture
def client(service: BusinessService) -> Iterator[TestClient]:
    app.dependency_overrides[get_business_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid4(), business_id=business_id, is_active=True
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_business_service, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_cenario_publicar_pagina_do_negocio(
    client: TestClient, repository: InMemoryBusinessRepository
) -> None:
    # Dado que cadastrei meu negócio (fixture "repository": Studio Aurora)
    business_path = f"/api/v1/businesses/{business_id}"

    # Quando adiciono logo
    # E adiciono descrição
    response = client.patch(
        business_path,
        json={
            "logo_url": "https://cdn.organizae.com/studio-aurora/logo.png",
            "description": "Cuidado, beleza e bem-estar em cada detalhe.",
        },
    )
    assert response.status_code == 200

    # E adiciono meus serviços (cadastrados pelo módulo de serviços)
    repository.services += [
        make_service("Corte + finalização", "120.00", 60),
        make_service("Coloração personalizada", "280.00", 120),
        make_service("Hidratação premium", "95.00", 45),
    ]

    # E adiciono WhatsApp
    # E adiciono Instagram
    response = client.patch(
        business_path, json={"whatsapp": "11988882018", "instagram": "@studioaurora"}
    )
    assert response.status_code == 200

    # E publico a página
    response = client.post(f"{business_path}/publish")
    assert response.status_code == 200
    assert response.json()["is_published"] is True
    assert response.json()["slug"] == "studio-aurora"

    # Então a página deve ficar disponível publicamente (sem login)
    app.dependency_overrides.pop(get_current_user)
    response = client.get("/api/v1/public/pages/studio-aurora")

    assert response.status_code == 200
    page = response.json()
    assert page["name"] == "Studio Aurora"
    assert page["logo_url"] == "https://cdn.organizae.com/studio-aurora/logo.png"
    assert page["description"] == "Cuidado, beleza e bem-estar em cada detalhe."
    assert page["whatsapp"] == "11988882018"
    assert page["instagram"] == "studioaurora"
    assert [service["name"] for service in page["services"]] == [
        "Coloração personalizada",
        "Corte + finalização",
        "Hidratação premium",
    ]


def test_unpublished_page_is_not_public(client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user)

    response = client.get("/api/v1/public/pages/studio-aurora")

    assert response.status_code == 404
    assert response.json() == {"detail": "Business page not found"}


def test_publish_without_description_and_services_explains_what_is_missing(
    client: TestClient,
) -> None:
    response = client.post(f"/api/v1/businesses/{business_id}/publish")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Business page cannot be published. Missing: description, services"
    }


def test_publish_requires_authentication(client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user)

    response = client.post(f"/api/v1/businesses/{business_id}/publish")

    assert response.status_code == 401


def test_cannot_publish_another_business(client: TestClient) -> None:
    response = client.post(f"/api/v1/businesses/{uuid4()}/publish")

    assert response.status_code == 404


@pytest.mark.parametrize("slug", ["Studio-Aurora", "studio_aurora", "-studio", "a" * 81])
def test_public_page_rejects_invalid_slug(client: TestClient, slug: str) -> None:
    app.dependency_overrides.pop(get_current_user)

    response = client.get(f"/api/v1/public/pages/{slug}")

    assert response.status_code == 422


def test_public_page_hides_inactive_services(
    service: BusinessService, repository: InMemoryBusinessRepository
) -> None:
    repository.businesses[business_id] = make_business(
        slug="studio-aurora",
        is_published=True,
        published_at=datetime.now(UTC),
        description="Cuidado e beleza.",
    )
    repository.services += [
        make_service("Corte", "120.00", 60),
        make_service("Escova antiga", "50.00", 30, is_active=False),
    ]

    page = service.get_public_page("studio-aurora")

    assert [item.name for item in page.services] == ["Corte"]


def test_publish_sets_slug_date_and_commits(
    service: BusinessService, repository: InMemoryBusinessRepository
) -> None:
    repository.businesses[business_id].description = "Cuidado e beleza."
    repository.services.append(make_service("Corte", "120.00", 60))

    business = service.publish(business_id)

    assert business.is_published is True
    assert business.slug == "studio-aurora"
    assert business.published_at is not None
    service.session.commit.assert_called_once_with()
    service.session.rollback.assert_not_called()


def test_publish_adds_suffix_when_slug_is_taken(
    service: BusinessService, repository: InMemoryBusinessRepository
) -> None:
    other = make_business(id=uuid4(), slug="studio-aurora")
    repository.businesses[other.id] = other
    repository.businesses[business_id].description = "Cuidado e beleza."
    repository.services.append(make_service("Corte", "120.00", 60))

    business = service.publish(business_id)

    assert business.slug == "studio-aurora-2"


def test_publish_twice_keeps_original_slug_and_date(
    service: BusinessService, repository: InMemoryBusinessRepository
) -> None:
    published_at = datetime(2026, 11, 1, tzinfo=UTC)
    repository.businesses[business_id] = make_business(
        slug="studio-aurora", is_published=True, published_at=published_at
    )

    business = service.publish(business_id)

    assert business.slug == "studio-aurora"
    assert business.published_at == published_at
    service.session.commit.assert_not_called()


def test_publish_with_blank_description_is_rejected_and_rolled_back(
    service: BusinessService, repository: InMemoryBusinessRepository
) -> None:
    repository.businesses[business_id].description = "   "
    repository.services.append(make_service("Corte", "120.00", 60))

    with pytest.raises(BusinessNotPublishableError) as error:
        service.publish(business_id)

    assert error.value.missing_fields == ["description"]
    assert repository.businesses[business_id].is_published is False
    service.session.commit.assert_not_called()
    service.session.rollback.assert_called_once_with()


def test_publish_unknown_business(service: BusinessService) -> None:
    with pytest.raises(BusinessNotFoundError):
        service.publish(uuid4())


def test_publish_locks_the_business_row() -> None:
    service = BusinessService(Mock(spec=Session))
    service.repository = Mock(spec=BusinessRepository)
    service.repository.get_by_id_for_update.return_value = None

    with pytest.raises(BusinessNotFoundError):
        service.publish(business_id)

    service.repository.get_by_id_for_update.assert_called_once_with(business_id)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Studio Aurora", "studio-aurora"),
        ("Salão da Ana", "salao-da-ana"),
        ("  Barbearia  do   Zé!! ", "barbearia-do-ze"),
        ("Unhas & Cia.", "unhas-cia"),
        ("!!!", "pagina"),
        ("a" * 100, "a" * 70),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("@studioaurora", "studioaurora"), (" studio.aurora_ ", "studio.aurora_")],
)
def test_instagram_is_saved_without_at_sign(value: str, expected: str) -> None:
    data = BusinessCreate(
        name="Studio",
        category_id=1,
        whatsapp="11988882018",
        service_mode="PRESENCIAL",
        instagram=value,
    )

    assert data.instagram == expected


@pytest.mark.parametrize(
    "value", ["", "@", "studio aurora", "studio-aurora", "a" * 31, "https://x.com"]
)
def test_invalid_instagram_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        BusinessUpdate(instagram=value)


def test_migration_adds_public_page_columns_and_constraints() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("7c3e9a1f5b28")
    assert revision.down_revision == "f6a2b91c408e"
    assert revision.revision in {
        item.revision
        for item in scripts.iterate_revisions("head", revision.down_revision)
    }

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()

    assert "ADD COLUMN instagram VARCHAR(30)" in sql
    assert "ADD COLUMN slug VARCHAR(80)" in sql
    assert "ADD COLUMN is_published BOOLEAN DEFAULT false NOT NULL" in sql
    assert "ADD COLUMN published_at TIMESTAMP WITH TIME ZONE" in sql
    assert "CONSTRAINT uq_businesses_slug UNIQUE (slug)" in sql
    assert "CONSTRAINT ck_businesses_slug_format CHECK" in sql
    assert "CONSTRAINT ck_businesses_published_page CHECK" in sql
