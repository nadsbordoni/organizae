"""Add monthly recurrences and identify generated financial competences."""

import sqlalchemy as sa

from alembic import op

revision: str = "9b72e4f1a603"
down_revision: str = "8a41d2c6e930"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_entries",
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
                name="ck_recurring_entries_type",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
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
            name="fk_recurring_entries_category_business_type",
        ),
        sa.UniqueConstraint(
            "id", "business_id", name="uq_recurring_entries_id_business"
        ),
        sa.CheckConstraint(
            "length(description) BETWEEN 1 AND 500 AND description = trim(description)",
            name="ck_recurring_entries_description",
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount <= 9999999999.99", name="ck_recurring_entries_amount"
        ),
        sa.CheckConstraint(
            "due_day BETWEEN 1 AND 31", name="ck_recurring_entries_due_day"
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_recurring_entries_dates",
        ),
    )
    op.create_index(
        "ix_recurring_entries_business_active",
        "recurring_entries",
        ["business_id", "is_active", "id"],
    )
    op.create_index(
        "ix_recurring_entries_business_category_type",
        "recurring_entries",
        ["business_id", "category_id", "type"],
    )
    op.add_column(
        "financial_entries", sa.Column("recurring_entry_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "financial_entries", sa.Column("competence", sa.Date(), nullable=True)
    )
    op.create_foreign_key(
        "fk_financial_entries_recurrence_business",
        "financial_entries",
        "recurring_entries",
        ["recurring_entry_id", "business_id"],
        ["id", "business_id"],
    )
    op.create_unique_constraint(
        "uq_financial_entries_recurrence_competence",
        "financial_entries",
        ["recurring_entry_id", "competence"],
    )
    op.create_check_constraint(
        "ck_financial_entries_recurrence_pair",
        "financial_entries",
        "(recurring_entry_id IS NULL AND competence IS NULL) OR (recurring_entry_id IS NOT NULL AND competence IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_financial_entries_competence_month",
        "financial_entries",
        sa.extract("day", sa.column("competence")) == 1,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_financial_entries_competence_month", "financial_entries", type_="check"
    )
    op.drop_constraint(
        "ck_financial_entries_recurrence_pair", "financial_entries", type_="check"
    )
    op.drop_constraint(
        "uq_financial_entries_recurrence_competence",
        "financial_entries",
        type_="unique",
    )
    op.drop_constraint(
        "fk_financial_entries_recurrence_business",
        "financial_entries",
        type_="foreignkey",
    )
    op.drop_column("financial_entries", "competence")
    op.drop_column("financial_entries", "recurring_entry_id")
    op.drop_table("recurring_entries")
