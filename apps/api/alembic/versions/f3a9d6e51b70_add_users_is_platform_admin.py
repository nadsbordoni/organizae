"""Mark which users are staff of the platform."""

import sqlalchemy as sa

from alembic import op

revision: str = "f3a9d6e51b70"
down_revision: str = "e1b7c4d92a58"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_platform_admin")
