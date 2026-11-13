"""Create financial categories and manual income/expense entries."""

import sqlalchemy as sa

from alembic import op

revision: str = "8a41d2c6e930"
down_revision: str = "7c3e9a1f5b28"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_appointments_id_business", "appointments", ["id", "business_id"]
    )
    op.create_table(
        "financial_categories",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "INCOME",
                "EXPENSE",
                native_enum=False,
                create_constraint=True,
                name="ck_financial_categories_type",
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.UniqueConstraint(
            "id", "business_id", "type", name="uq_financial_categories_id_business_type"
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 150 AND name = trim(name)",
            name="ck_financial_categories_name",
        ),
    )
    op.create_index(
        "uq_financial_categories_business_name_type",
        "financial_categories",
        ["business_id", sa.text("lower(name)"), "type"],
        unique=True,
    )
    op.create_table(
        "financial_entries",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "INCOME",
                "EXPENSE",
                native_enum=False,
                create_constraint=True,
                name="ck_financial_entries_type",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PAID",
                "CANCELLED",
                native_enum=False,
                create_constraint=True,
                name="ck_financial_entries_status",
            ),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(
            ["category_id", "business_id", "type"],
            [
                "financial_categories.id",
                "financial_categories.business_id",
                "financial_categories.type",
            ],
            name="fk_financial_entries_category_business_type",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id", "business_id"],
            ["appointments.id", "appointments.business_id"],
            name="fk_financial_entries_appointment_business",
        ),
        sa.CheckConstraint(
            "length(description) BETWEEN 1 AND 500 AND description = trim(description)",
            name="ck_financial_entries_description",
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount <= 9999999999.99", name="ck_financial_entries_amount"
        ),
        sa.CheckConstraint(
            "(status = 'PAID' AND paid_at IS NOT NULL) OR (status IN ('PENDING', 'CANCELLED') AND paid_at IS NULL)",
            name="ck_financial_entries_payment",
        ),
    )
    for name, columns in (
        ("ix_financial_entries_business_due_date", ["business_id", "due_date", "id"]),
        (
            "ix_financial_entries_business_category_type",
            ["business_id", "category_id", "type"],
        ),
        ("ix_financial_entries_business_status", ["business_id", "status"]),
        (
            "ix_financial_entries_business_appointment",
            ["business_id", "appointment_id"],
        ),
    ):
        op.create_index(name, "financial_entries", columns)


def downgrade() -> None:
    op.drop_table("financial_entries")
    op.drop_index(
        "uq_financial_categories_business_name_type", table_name="financial_categories"
    )
    op.drop_table("financial_categories")
    op.drop_constraint("uq_appointments_id_business", "appointments", type_="unique")
