"""Add the tax id (CPF or CNPJ) and the city asked at sign-up to businesses."""

import sqlalchemy as sa

from alembic import op

revision: str = "e27084a70711"
down_revision: str = "9d329c467d49"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Nullable: businesses created before sign-up asked for them have neither.
    op.add_column("businesses", sa.Column("tax_id", sa.String(14), nullable=True))
    op.add_column("businesses", sa.Column("city", sa.String(100), nullable=True))
    # CPF: 11 digits. CNPJ: 12 letters or digits plus 2 check digits, the
    # alphanumeric format the Receita Federal issues since July 2026.
    op.create_check_constraint(
        "ck_businesses_tax_id_format",
        "businesses",
        "tax_id ~ '^([0-9]{11}|[0-9A-Z]{12}[0-9]{2})$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_businesses_tax_id_format", "businesses", type_="check")
    op.drop_column("businesses", "city")
    op.drop_column("businesses", "tax_id")
