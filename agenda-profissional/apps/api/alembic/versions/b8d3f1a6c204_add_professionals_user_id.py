"""Link a professional to the user that logs in as them.

The column is optional: only professionals with their own access have it.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b8d3f1a6c204"
down_revision: str = "f3a9d6e51b70"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("professionals", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_professionals_user_id_users",
        "professionals",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_professionals_user_id", "professionals", ["user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_professionals_user_id", "professionals", type_="unique")
    op.drop_constraint(
        "fk_professionals_user_id_users", "professionals", type_="foreignkey"
    )
    op.drop_column("professionals", "user_id")
