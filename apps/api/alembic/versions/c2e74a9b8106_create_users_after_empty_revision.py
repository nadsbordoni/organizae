"""Create users after the historical empty users revision.

Revision ID: c2e74a9b8106
Revises: f0dbf1d6b150

The empty revision is preserved so databases already stamped at that revision
can receive the table through a normal upgrade.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "c2e74a9b8106"
down_revision: str = "f0dbf1d6b150"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
