from collections.abc import Iterator
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
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.schemas import (
    BusinessCreate,
    BusinessUpdate,
    PublicPageResponse,
)
from app.modules.businesses.service import BusinessService
from app.modules.users.models import User

business_id = UUID("8ccacb20-1d36-44a7-9d32-08ac5f6bf15e")
base = {
    "name": "Studio Aurora",
    "category_id": 3,
    "whatsapp": "81999999999",
    "service_mode": "PRESENCIAL",
}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("529.982.247-25", "52998224725"),
        ("52998224725", "52998224725"),
        ("11.222.333/0001-81", "11222333000181"),
        # Alphanumeric CNPJ, issued since July 2026.
        ("12.ABC.345/01DE-35", "12ABC34501DE35"),
        ("12.abc.345/01de-35", "12ABC34501DE35"),
    ],
)
def test_tax_id_is_saved_without_punctuation(value: str, expected: str) -> None:
    assert BusinessCreate(**base, tax_id=value).tax_id == expected


@pytest.mark.parametrize(
    "value",
    [
        "529.982.247-24",
        "11.222.333/0001-82",
        "12.ABC.345/01DE-36",
        "111.111.111-11",
        "00.000.000/0000-00",
        "12.ABC.345/01DE-3A",
        "1234567890",
        "AB.222.333/0001-81",
        "",
        "1" * 30,
    ],
)
def test_invalid_tax_id_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        BusinessCreate(**base, tax_id=value)
    with pytest.raises(ValidationError):
        BusinessUpdate(tax_id=value)


def test_city_is_trimmed_and_cannot_be_blank() -> None:
    assert BusinessCreate(**base, city="  Recife ").city == "Recife"
    with pytest.raises(ValidationError):
        BusinessCreate(**base, city="   ")
    with pytest.raises(ValidationError):
        BusinessUpdate(city="x" * 101)


def test_tax_id_and_city_stay_optional_for_existing_clients() -> None:
    business = BusinessCreate(**base)
    assert business.tax_id is None
    assert business.city is None


def test_tax_id_is_not_on_the_public_page() -> None:
    assert "tax_id" not in PublicPageResponse.model_fields


@pytest.fixture
def client() -> Iterator[tuple[TestClient, Mock]]:
    service = Mock(spec=BusinessService)
    service.create_for_user.return_value = Business(
        id=business_id,
        name="Studio Aurora",
        category_id=3,
        whatsapp="81999999999",
        service_mode=ServiceMode.PRESENCIAL,
        city="Recife",
        tax_id="52998224725",
    )
    current_user = User(id=uuid4(), business_id=None, is_active=True)
    app.dependency_overrides[get_business_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as test_client:
            yield test_client, service
    finally:
        app.dependency_overrides.pop(get_business_service)
        app.dependency_overrides.pop(get_current_user)


def test_sign_up_sends_normalized_tax_id_and_city(
    client: tuple[TestClient, Mock],
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/v1/businesses",
        json={**base, "tax_id": "529.982.247-25", "city": " Recife "},
    )

    assert response.status_code == 201
    assert response.json()["tax_id"] == "52998224725"
    assert response.json()["city"] == "Recife"
    sent = service.create_for_user.call_args.args[0]
    assert (sent.tax_id, sent.city) == ("52998224725", "Recife")


def test_sign_up_with_invalid_tax_id_does_not_call_service(
    client: tuple[TestClient, Mock],
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/v1/businesses", json={**base, "tax_id": "529.982.247-24"}
    )

    assert response.status_code == 422
    service.create_for_user.assert_not_called()


def test_migration_adds_nullable_tax_id_and_city_with_format_check() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("e27084a70711")
    assert revision.down_revision == "9d329c467d49"
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

    assert "ADD COLUMN tax_id VARCHAR(14);" in sql
    assert "ADD COLUMN city VARCHAR(100);" in sql
    assert "CONSTRAINT ck_businesses_tax_id_format CHECK" in sql
    assert "[0-9A-Z]{12}[0-9]{2}" in sql
