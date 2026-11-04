"""Create business hours and appointments for online booking."""

import sqlalchemy as sa

from alembic import op

revision: str = "b3d91f7a2c45"
down_revision: str = "e6f8a2c93104"
branch_labels: str | None = None
depends_on: str | None = None

appointment_status = sa.Enum(
    "PENDING", "CONFIRMED", "CANCELLED", "BLOCKED", name="appointmentstatus"
)
appointment_source = sa.Enum("ONLINE", "PANEL", name="appointmentsource")


def upgrade() -> None:
    # Required to combine uuid equality with range overlap in one exclusion constraint.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "business_hours",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_business_hours_weekday"),
        sa.CheckConstraint("closes_at > opens_at", name="ck_business_hours_range"),
    )
    op.create_index(
        "ix_business_hours_business_weekday",
        "business_hours",
        ["business_id", "weekday"],
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("professional_id", sa.Uuid(), nullable=True),
        sa.Column("service_id", sa.Uuid(), nullable=True),
        sa.Column("customer_name", sa.String(120), nullable=True),
        sa.Column("customer_phone", sa.String(13), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", appointment_status, nullable=False),
        sa.Column("source", appointment_source, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(
            ["professional_id", "business_id"],
            ["professionals.id", "professionals.business_id"],
            name="fk_appointments_professional_business",
        ),
        sa.ForeignKeyConstraint(
            ["service_id", "business_id"],
            ["services.id", "services.business_id"],
            name="fk_appointments_service_business",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_appointments_range"),
        sa.CheckConstraint(
            "status = 'BLOCKED' OR (professional_id IS NOT NULL"
            " AND service_id IS NOT NULL AND customer_name IS NOT NULL"
            " AND customer_phone IS NOT NULL)",
            name="ck_appointments_customer",
        ),
    )
    # Two bookings of the same professional can never overlap, even under concurrency.
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_professional_overlap "
        "EXCLUDE USING gist (professional_id WITH =, tstzrange(starts_at, ends_at) WITH &&) "
        "WHERE (status <> 'CANCELLED')"
    )
    op.create_index(
        "ix_appointments_business_starts", "appointments", ["business_id", "starts_at"]
    )
    op.create_index(
        "ix_appointments_business_phone",
        "appointments",
        ["business_id", "customer_phone"],
    )


def downgrade() -> None:
    op.drop_table("appointments")
    op.drop_index("ix_business_hours_business_weekday", table_name="business_hours")
    op.drop_table("business_hours")
    appointment_source.drop(op.get_bind(), checkfirst=True)
    appointment_status.drop(op.get_bind(), checkfirst=True)
