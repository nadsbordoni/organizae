from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


@pytest.fixture
def revision() -> ModuleType:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "a8f14c2d9e60"
    return script.get_revision("a8f14c2d9e60").module


def test_migration_renders_postgresql_sql_without_connecting(
    revision: ModuleType,
) -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.upgrade()
    sql = output.getvalue()

    assert sql.index("LOCK TABLE") < sql.index("ADD COLUMN")
    for table in ("businesses", "professionals", "services"):
        assert f"ALTER TABLE {table} ALTER COLUMN id TYPE UUID USING _uuid_id" in sql
        assert (
            f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT gen_random_uuid()" in sql
        )
        assert f"DROP TABLE {table}" not in sql
    for table, column, parent in (
        ("professionals", "business_id", "businesses"),
        ("services", "business_id", "businesses"),
        ("professional_services", "professional_id", "professionals"),
        ("professional_services", "service_id", "services"),
        ("professional_services", "business_id", "businesses"),
    ):
        mapping = f"UPDATE {table} AS child SET _uuid_{column} = parent._uuid_id"
        conversion = (
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE UUID USING _uuid_{column}"
        )
        assert mapping in sql
        assert f"FROM {parent} AS parent WHERE child.{column} = parent.id" in sql
        assert sql.index(mapping) < sql.index(conversion)
    assert (
        "FOREIGN KEY(professional_id, business_id) REFERENCES professionals (id, business_id)"
        in sql
    )
    assert (
        "FOREIGN KEY(service_id, business_id) REFERENCES services (id, business_id)"
        in sql
    )
    assert "UNIQUE (id, business_id)" in sql
    assert "category_id" not in sql
    assert "business_categories" not in sql
    assert "servicemode" not in sql


def test_downgrade_fails_before_emitting_sql(revision: ModuleType) -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with (
        Operations.context(context),
        pytest.raises(NotImplementedError, match="backup"),
    ):
        revision.downgrade()
    assert output.getvalue() == ""
