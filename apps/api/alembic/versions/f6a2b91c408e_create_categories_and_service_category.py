"""Create product/service categories scoped to businesses and optional service links."""

import sqlalchemy as sa

from alembic import op

revision: str = "f6a2b91c408e"
down_revision: str = "d4a91c8e720f"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.UniqueConstraint("id", "business_id", name="uq_categories_id_business"),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 150 AND name = trim(name)",
            name="ck_categories_name",
        ),
    )
    op.create_index(
        "uq_categories_business_name",
        "categories",
        ["business_id", sa.text("lower(name)")],
        unique=True,
    )
    op.add_column("services", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_services_category_business",
        "services",
        "categories",
        ["category_id", "business_id"],
        ["id", "business_id"],
    )
    op.create_index(
        "ix_services_business_category", "services", ["business_id", "category_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_services_business_category", table_name="services")
    op.drop_constraint("fk_services_category_business", "services", type_="foreignkey")
    op.drop_column("services", "category_id")
    op.drop_index("uq_categories_business_name", table_name="categories")
    op.drop_table("categories")
