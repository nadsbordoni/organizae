"""Add birth date, referral and WhatsApp consent to clients."""

import sqlalchemy as sa

from alembic import op

revision: str = "0b07952a538e"
down_revision: str = "f3a9d6e51b70"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("clients", sa.Column("referral", sa.String(20), nullable=True))
    # Existing clients never gave consent, so they start opted out.
    op.add_column(
        "clients",
        sa.Column(
            "whatsapp_opt_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_clients_referral",
        "clients",
        "referral IN ('INSTAGRAM', 'REFERRAL', 'GOOGLE', 'WHATSAPP', 'OTHER')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_clients_referral", "clients", type_="check")
    op.drop_column("clients", "whatsapp_opt_in")
    op.drop_column("clients", "referral")
    op.drop_column("clients", "birth_date")
