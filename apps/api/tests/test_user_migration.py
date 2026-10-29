from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def test_corrective_migration_preserves_empty_revision_and_renders_users_table() -> (
    None
):
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("c2e74a9b8106")
    assert revision.revision in {
        item.revision for item in scripts.iterate_revisions("head", "f0dbf1d6b150")
    }
    assert revision.down_revision == "f0dbf1d6b150"
    assert scripts.get_revision("f0dbf1d6b150").down_revision == "a8f14c2d9e60"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE users" in sql
    assert "id UUID NOT NULL" in sql
    assert "password_hash VARCHAR(255) NOT NULL" in sql
    assert "business_id UUID," in sql
    assert "UNIQUE (business_id)" in sql
    assert "FOREIGN KEY(business_id) REFERENCES businesses (id)" in sql
    assert "CREATE UNIQUE INDEX ix_users_email ON users (email)" in sql
    assert "DROP" not in sql
    assert "ALTER TABLE businesses" not in sql
