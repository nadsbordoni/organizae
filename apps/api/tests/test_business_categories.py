from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
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
    from app.modules.business_categories.route import get_business_category_service

from app.modules.business_categories.models import BusinessCategory
from app.modules.business_categories.repository import BusinessCategoryRepository
from app.modules.business_categories.service import BusinessCategoryService


@pytest.fixture
def client() -> Iterator[tuple[TestClient, Mock]]:
    service = Mock(spec=BusinessCategoryService)
    service.list.return_value = [
        BusinessCategory(id=1, name="Beleza e bem-estar"),
        BusinessCategory(id=6, name="Outro"),
    ]
    app.dependency_overrides[get_business_category_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        app.dependency_overrides.pop(get_business_category_service)


def test_categories_are_listed_without_authentication(
    client: tuple[TestClient, Mock],
) -> None:
    test_client, service = client
    response = test_client.get("/api/v1/business-categories")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "name": "Beleza e bem-estar"},
        {"id": 6, "name": "Outro"},
    ]
    service.list.assert_called_once_with()
    operation = app.openapi()["paths"]["/api/v1/business-categories"]["get"]
    assert "security" not in operation


def test_repository_lists_in_seed_order() -> None:
    session = Mock(spec=Session)
    session.scalars.return_value.all.return_value = []

    assert BusinessCategoryRepository(session).list() == []

    statement = session.scalars.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ORDER BY business_categories.id" in sql
    session.commit.assert_not_called()


def migration_sql(operation: str) -> str:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("9d329c467d49")
    assert revision.down_revision == "9b72e4f1a603"
    assert revision.revision in {
        item.revision
        for item in scripts.iterate_revisions("head", revision.down_revision)
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        getattr(revision.module, operation)()
    return output.getvalue()


def test_migration_seeds_sign_up_categories_once() -> None:
    sql = migration_sql("upgrade")

    assert "setval(pg_get_serial_sequence('business_categories', 'id')" in sql
    assert "INSERT INTO business_categories (name) VALUES" in sql
    for name in ("Beleza e bem-estar", "Cabelo", "Unhas", "Estética", "Barbearia"):
        assert f"'{name}'" in sql
    assert "ON CONFLICT (name) DO NOTHING" in sql


def test_downgrade_keeps_categories_used_by_a_business() -> None:
    sql = migration_sql("downgrade")

    assert "DELETE FROM business_categories" in sql
    assert "IN ('Beleza e bem-estar', 'Cabelo', 'Unhas', 'Estética'" in sql
    assert "NOT (EXISTS (SELECT" in sql
    assert "businesses.category_id = business_categories.id" in sql
