"""Create clients scoped to a business, without changing appointments."""

import sqlalchemy as sa

from alembic import op

revision: str = "d4a91c8e720f"
down_revision: str = "b3d91f7a2c45"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(13), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.UniqueConstraint("business_id", "phone", name="uq_clients_business_phone"),
        sa.CheckConstraint(
            "length(phone) BETWEEN 10 AND 13", name="ck_clients_phone_length"
        ),
    )
    op.create_index(
        "ix_clients_business_name_id", "clients", ["business_id", "name", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_clients_business_name_id", table_name="clients")
    op.drop_table("clients")
