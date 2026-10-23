"""Convert entity IDs and their references to UUID v4 without losing rows.

Revision ID: a8f14c2d9e60
Revises: d7d890e644e1

Requires PostgreSQL 13+ (built-in gen_random_uuid). Run with application writes
stopped: the tables are exclusively locked until the migration commits.
Original integer IDs are replaced; restore a backup to recover those IDs.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "a8f14c2d9e60"
down_revision: str = "d7d890e644e1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    primary_tables = ("businesses", "professionals", "services")
    references = (
        ("professionals", "business_id", "businesses"),
        ("services", "business_id", "businesses"),
        ("professional_services", "professional_id", "professionals"),
        ("professional_services", "service_id", "services"),
        ("professional_services", "business_id", "businesses"),
    )

    # Keep the integer-to-UUID mapping stable while rewriting all references.
    op.execute(
        "LOCK TABLE businesses, professionals, services, professional_services "
        "IN ACCESS EXCLUSIVE MODE"
    )
    for table in primary_tables:
        op.add_column(
            table,
            sa.Column(
                "_uuid_id",
                sa.Uuid(),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
        )

    for table, column, parent in references:
        temporary_column = f"_uuid_{column}"
        op.add_column(table, sa.Column(temporary_column, sa.Uuid(), nullable=True))
        op.execute(
            f"UPDATE {table} AS child SET {temporary_column} = parent._uuid_id "
            f"FROM {parent} AS parent WHERE child.{column} = parent.id"
        )
        # Abort before replacing IDs if any reference could not be mapped.
        op.alter_column(table, temporary_column, nullable=False)

    op.drop_constraint(
        "fk_professional_services_professional_business",
        "professional_services",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_professional_services_service_business",
        "professional_services",
        type_="foreignkey",
    )
    for table in ("professionals", "services"):
        op.drop_constraint(f"{table}_business_id_fkey", table, type_="foreignkey")
        op.drop_constraint(f"uq_{table}_id_business", table, type_="unique")

    for table in primary_tables:
        # Integer sequence defaults cannot be cast to UUID.
        op.alter_column(table, "id", server_default=None)
        op.alter_column(
            table,
            "id",
            existing_type=sa.Integer(),
            type_=sa.Uuid(),
            postgresql_using="_uuid_id",
            existing_nullable=False,
        )
        op.alter_column(table, "id", server_default=sa.text("gen_random_uuid()"))

    for table, column, _parent in references:
        op.alter_column(
            table,
            column,
            existing_type=sa.Integer(),
            type_=sa.Uuid(),
            postgresql_using=f"_uuid_{column}",
            existing_nullable=False,
        )

    for table in ("professionals", "services"):
        op.create_unique_constraint(
            f"uq_{table}_id_business", table, ["id", "business_id"]
        )
        op.create_foreign_key(
            f"{table}_business_id_fkey", table, "businesses", ["business_id"], ["id"]
        )
    op.create_foreign_key(
        "fk_professional_services_professional_business",
        "professional_services",
        "professionals",
        ["professional_id", "business_id"],
        ["id", "business_id"],
    )
    op.create_foreign_key(
        "fk_professional_services_service_business",
        "professional_services",
        "services",
        ["service_id", "business_id"],
        ["id", "business_id"],
    )

    for table, column, _parent in references:
        op.drop_column(table, f"_uuid_{column}")
    for table in primary_tables:
        op.drop_column(table, "_uuid_id")
        op.execute(f"DROP SEQUENCE IF EXISTS {table}_id_seq")


def downgrade() -> None:
    raise NotImplementedError(
        "Original integer IDs cannot be recovered from UUIDs. "
        "Restore a backup taken before this migration to recover those IDs."
    )
