"""Create notifications for the business owner, starting with new online bookings."""

import sqlalchemy as sa

from alembic import op

revision: str = "c7e4a2b91d38"
down_revision: str = "f3a9d6e51b70"
branch_labels: str | None = None
depends_on: str | None = None

notification_kind = sa.Enum("BOOKING_CREATED", name="notificationkind")


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=False),
        sa.Column("kind", notification_kind, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(
            ["appointment_id", "business_id"],
            ["appointments.id", "appointments.business_id"],
            name="fk_notifications_appointment_business",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_notifications_business_created",
        "notifications",
        ["business_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_business_created", table_name="notifications")
    op.drop_table("notifications")
    notification_kind.drop(op.get_bind(), checkfirst=True)
