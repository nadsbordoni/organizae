from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

REVISION = "0b07952a538e"


def render(direction: str) -> str:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(revision.module, direction)()
    return output.getvalue()


def test_profile_migration_sits_on_top_of_the_history() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision(REVISION).down_revision == "f3a9d6e51b70"
    assert scripts.get_heads() == [REVISION]


def test_profile_migration_only_adds_nullable_or_defaulted_columns() -> None:
    sql = render("upgrade")
    assert "ALTER TABLE clients ADD COLUMN birth_date DATE" in sql
    assert "ALTER TABLE clients ADD COLUMN referral VARCHAR(20)" in sql
    assert (
        "ALTER TABLE clients ADD COLUMN whatsapp_opt_in BOOLEAN DEFAULT false NOT NULL"
        in sql
    )
    assert "ck_clients_referral" in sql
    assert "DROP" not in sql


def test_profile_migration_downgrade_only_removes_the_new_columns() -> None:
    sql = render("downgrade")
    assert "DROP CONSTRAINT ck_clients_referral" in sql
    for column in ("whatsapp_opt_in", "referral", "birth_date"):
        assert f"ALTER TABLE clients DROP COLUMN {column}" in sql
    assert "DROP TABLE" not in sql
