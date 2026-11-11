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
    revision = scripts.get_revision("8a41d2c6e930")
    assert revision.down_revision == "7c3e9a1f5b28"
    assert revision.revision in {
        item.revision
        for item in scripts.iterate_revisions("head", revision.down_revision)
    }
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(revision.module, operation)()
    return output.getvalue()


def test_financial_upgrade_is_additive_and_preserves_existing_appointments():
    sql = migration_sql("upgrade")
    assert "CREATE TABLE financial_categories" in sql
    assert "CREATE TABLE financial_entries" in sql
    assert "amount NUMERIC(12, 2) NOT NULL" in sql
    assert "paid_at TIMESTAMP WITH TIME ZONE," in sql
    assert "appointment_id UUID," in sql
    assert "DEFAULT 'PENDING' NOT NULL" in sql
    assert "UNIQUE (id, business_id)" in sql
    assert "UNIQUE (id, business_id, type)" in sql
    assert (
        "FOREIGN KEY(category_id, business_id, type) REFERENCES financial_categories (id, business_id, type)"
        in sql
    )
    assert (
        "FOREIGN KEY(appointment_id, business_id) REFERENCES appointments (id, business_id)"
        in sql
    )
    assert "ON financial_categories (business_id, lower(name), type)" in sql
    assert "'PENDING', 'PAID', 'CANCELLED'" in sql
    assert "ck_financial_entries_payment" in sql
    assert "ON DELETE CASCADE" not in sql
    assert "CREATE TYPE" not in sql
    for mutation in ("DELETE ", "UPDATE ", "DROP ", "TRUNCATE "):
        assert mutation not in sql


def test_financial_downgrade_only_removes_new_financial_objects():
    sql = migration_sql("downgrade")
    assert sql.index("DROP TABLE financial_entries") < sql.index(
        "DROP TABLE financial_categories"
    )
    assert "ALTER TABLE appointments DROP CONSTRAINT uq_appointments_id_business" in sql
    assert "DROP TABLE appointments" not in sql
    assert "DROP TABLE businesses" not in sql
