from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def render_migration(operation):
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("9b72e4f1a603")
    assert revision.down_revision == "8a41d2c6e930"
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


def test_recurring_upgrade_preserves_manual_entries_and_enforces_tenant_and_competence():
    sql = render_migration("upgrade")
    assert "CREATE TABLE recurring_entries" in sql
    assert "amount NUMERIC(12, 2) NOT NULL" in sql
    assert "ADD COLUMN recurring_entry_id UUID;" in sql
    assert "ADD COLUMN competence DATE;" in sql
    assert "UNIQUE (recurring_entry_id, competence)" in sql
    assert (
        "FOREIGN KEY(recurring_entry_id, business_id) REFERENCES recurring_entries (id, business_id)"
        in sql
    )
    assert (
        "FOREIGN KEY(category_id, business_id, type) REFERENCES financial_categories (id, business_id, type)"
        in sql
    )
    assert "ck_financial_entries_recurrence_pair" in sql
    assert "EXTRACT(day FROM competence) = 1" in sql
    assert "ck_recurring_entries_due_day" in sql and "ck_recurring_entries_dates" in sql
    assert "CREATE TYPE" not in sql and "ON DELETE CASCADE" not in sql
    for mutation in ("DELETE ", "UPDATE ", "DROP ", "TRUNCATE "):
        assert mutation not in sql


def test_recurring_downgrade_only_removes_new_objects_in_dependency_order():
    sql = render_migration("downgrade")
    assert sql.index(
        "DROP CONSTRAINT fk_financial_entries_recurrence_business"
    ) < sql.index("DROP TABLE recurring_entries")
    assert "DROP COLUMN competence" in sql and "DROP COLUMN recurring_entry_id" in sql
    assert (
        "DROP TABLE financial_entries" not in sql
        and "DROP TABLE financial_categories" not in sql
    )
    assert "DELETE " not in sql and "UPDATE " not in sql
