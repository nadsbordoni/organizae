"""Seed the business categories offered at sign-up."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9d329c467d49"
down_revision: str = "9b72e4f1a603"
branch_labels: str | None = None
depends_on: str | None = None

BUSINESS_CATEGORIES = (
    "Beleza e bem-estar",
    "Cabelo",
    "Unhas",
    "Estética",
    "Barbearia",
    "Outro",
)

categories = sa.table(
    "business_categories",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)
businesses = sa.table("businesses", sa.column("category_id", sa.Integer))


def names() -> list[sa.ColumnElement[str]]:
    # Literals, so the names also appear in the SQL of `alembic upgrade --sql`.
    return [op.inline_literal(name) for name in BUSINESS_CATEGORIES]


def upgrade() -> None:
    # Development databases may have categories inserted by hand with explicit ids,
    # which leaves the sequence behind; realign it before inserting.
    op.execute(
        "SELECT setval(pg_get_serial_sequence('business_categories', 'id'), "
        "COALESCE((SELECT MAX(id) FROM business_categories), 0) + 1, false)"
    )
    op.execute(
        postgresql.insert(categories)
        .values([{"name": name} for name in names()])
        .on_conflict_do_nothing(index_elements=["name"])
    )


def downgrade() -> None:
    # Categories already chosen by a business stay, to keep the foreign key valid.
    op.execute(
        categories.delete().where(
            categories.c.name.in_(names()),
            ~sa.exists().where(businesses.c.category_id == categories.c.id),
        )
    )
