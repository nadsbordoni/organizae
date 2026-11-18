"""Link a user account to a professional, so professionals can log in."""

import sqlalchemy as sa

from alembic import op

revision: str = "4d8e2b7c1a95"
down_revision: str = "9b72e4f1a603"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("professional_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_users_professional_id", "users", "professionals", ["professional_id"], ["id"]
    )
    op.create_unique_constraint("uq_users_professional_id", "users", ["professional_id"])
    op.create_check_constraint(
        "ck_users_single_role",
        "users",
        "business_id IS NULL OR professional_id IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_single_role", "users", type_="check")
    op.drop_constraint("uq_users_professional_id", "users", type_="unique")
    op.drop_constraint("fk_users_professional_id", "users", type_="foreignkey")
    op.drop_column("users", "professional_id")
