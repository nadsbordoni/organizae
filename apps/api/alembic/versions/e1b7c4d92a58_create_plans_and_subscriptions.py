"""Create plans, subscriptions and gateway events; start a trial for every business."""

import sqlalchemy as sa

from alembic import op

revision: str = "e1b7c4d92a58"
down_revision: str = "c5b8e1a47d93"
branch_labels: str | None = None
depends_on: str | None = None

DEFAULT_PRICE_CENTS = 4990
TRIAL_DAYS = 15


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.CheckConstraint("price_cents >= 0", name="ck_plans_price_cents"),
    )
    op.create_table(
        "subscriptions",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gateway_customer_id", sa.String(100), nullable=True),
        sa.Column("gateway_subscription_id", sa.String(100), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.UniqueConstraint("business_id", name="uq_subscriptions_business_id"),
        sa.CheckConstraint(
            "status IN ('TRIALING', 'ACTIVE', 'PAST_DUE', 'SUSPENDED', 'CANCELED')",
            name="ck_subscriptions_status",
        ),
    )
    op.create_table(
        "gateway_events",
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.execute(
        "INSERT INTO plans (code, name, price_cents) "
        f"VALUES ('standard', 'Organizaê', {DEFAULT_PRICE_CENTS})"
    )
    # Businesses that already exist start a trial instead of being blocked.
    op.execute(
        "INSERT INTO subscriptions (business_id, plan_id, status, trial_ends_at) "
        f"SELECT b.id, p.id, 'TRIALING', now() + interval '{TRIAL_DAYS} days' "
        "FROM businesses b CROSS JOIN plans p WHERE p.code = 'standard'"
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
    op.drop_table("gateway_events")
    op.drop_table("plans")
