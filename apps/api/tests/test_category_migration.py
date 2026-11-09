from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def migration_sql(operation: str) -> str:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("f6a2b91c408e")
    assert revision.down_revision == "d4a91c8e720f"
    assert revision.revision in {
        item.revision for item in scripts.iterate_revisions("head", "d4a91c8e720f")
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        getattr(revision.module, operation)()
    return output.getvalue()


def test_upgrade_preserves_services_and_adds_nullable_tenant_scoped_category() -> None:
    sql = migration_sql("upgrade")
    assert "CREATE TABLE categories" in sql
    assert "id UUID DEFAULT gen_random_uuid() NOT NULL" in sql
    assert "business_id UUID NOT NULL" in sql
    assert "name VARCHAR(150) NOT NULL" in sql
    assert "FOREIGN KEY(business_id) REFERENCES businesses (id)" in sql
    assert "CONSTRAINT uq_categories_id_business UNIQUE (id, business_id)" in sql
    assert (
        "CREATE UNIQUE INDEX uq_categories_business_name ON categories (business_id, lower(name))"
        in sql
    )
    assert "ALTER TABLE services ADD COLUMN category_id UUID;" in sql
    assert (
        "FOREIGN KEY(category_id, business_id) REFERENCES categories (id, business_id)"
        in sql
    )
    assert (
        "CREATE INDEX ix_services_business_category ON services (business_id, category_id)"
        in sql
    )
    assert "ON DELETE CASCADE" not in sql
    assert "ON DELETE SET NULL" not in sql
    assert "business_categories" not in sql
    for destructive in ("UPDATE ", "DELETE ", "DROP ", "TRUNCATE "):
        assert destructive not in sql


def test_downgrade_removes_category_link_before_categories_without_dropping_services() -> (
    None
):
    sql = migration_sql("downgrade")
    assert sql.index("DROP CONSTRAINT fk_services_category_business") < sql.index(
        "DROP COLUMN category_id"
    )
    assert sql.index("DROP COLUMN category_id") < sql.index("DROP TABLE categories")
    assert "DROP TABLE services" not in sql
    assert "business_categories" not in sql
