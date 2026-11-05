from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def test_clients_migration_renders_postgresql_without_changing_existing_tables() -> (
    None
):
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("d4a91c8e720f")
    assert revision.down_revision == "b3d91f7a2c45"
    assert revision.revision in {
        item.revision for item in scripts.iterate_revisions("head", "b3d91f7a2c45")
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE clients" in sql
    assert "id UUID DEFAULT gen_random_uuid() NOT NULL" in sql
    assert "business_id UUID NOT NULL" in sql
    assert "name VARCHAR(120) NOT NULL" in sql
    assert "phone VARCHAR(13) NOT NULL" in sql
    assert "email VARCHAR(255)," in sql
    assert "notes TEXT," in sql
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    assert "FOREIGN KEY(business_id) REFERENCES businesses (id)" in sql
    assert "CONSTRAINT uq_clients_business_phone UNIQUE (business_id, phone)" in sql
    assert (
        "CREATE INDEX ix_clients_business_name_id ON clients (business_id, name, id)"
        in sql
    )
    assert "ALTER TABLE" not in sql
    assert "appointments" not in sql
    assert "DROP" not in sql


def test_clients_migration_downgrade_only_removes_clients() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    revision = ScriptDirectory.from_config(config).get_revision("d4a91c8e720f")
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.downgrade()
    assert output.getvalue().strip() == (
        "DROP INDEX ix_clients_business_name_id;\n\nDROP TABLE clients;"
    )
