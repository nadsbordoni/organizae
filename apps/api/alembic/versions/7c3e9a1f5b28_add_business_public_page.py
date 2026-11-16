"""Add Instagram and public page publication fields to businesses."""

import sqlalchemy as sa

from alembic import op

revision: str = "7c3e9a1f5b28"
down_revision: str = "f6a2b91c408e"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("instagram", sa.String(30), nullable=True))
    op.add_column("businesses", sa.Column("slug", sa.String(80), nullable=True))
    op.add_column(
        "businesses",
        sa.Column(
            "is_published",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "businesses",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_businesses_slug", "businesses", ["slug"])
    op.create_check_constraint(
        "ck_businesses_slug_format",
        "businesses",
        "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
    )
    op.create_check_constraint(
        "ck_businesses_published_page",
        "businesses",
        "NOT is_published OR (slug IS NOT NULL AND published_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_businesses_published_page", "businesses", type_="check")
    op.drop_constraint("ck_businesses_slug_format", "businesses", type_="check")
    op.drop_constraint("uq_businesses_slug", "businesses", type_="unique")
    op.drop_column("businesses", "published_at")
    op.drop_column("businesses", "is_published")
    op.drop_column("businesses", "slug")
    op.drop_column("businesses", "instagram")
