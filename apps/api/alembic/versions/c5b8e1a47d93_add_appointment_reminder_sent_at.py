"""Add reminder_sent_at to appointments."""

import sqlalchemy as sa

from alembic import op

revision: str = "c5b8e1a47d93"
down_revision: str = "9b72e4f1a603"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "reminder_sent_at")
