"""translate service mode enum to portuguese

Revision ID: d7d890e644e1
Revises: 37dc4c8c615d
Create Date: 2026-10-22 12:12:26.415218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7d890e644e1'
down_revision: Union[str, Sequence[str], None] = '37dc4c8c615d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE servicemode RENAME VALUE 'IN_PERSON' TO 'PRESENCIAL'"
    )
    op.execute(
        "ALTER TYPE servicemode RENAME VALUE 'BOTH' TO 'HIBRIDO'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TYPE servicemode RENAME VALUE 'PRESENCIAL' TO 'IN_PERSON'"
    )
    op.execute(
        "ALTER TYPE servicemode RENAME VALUE 'HIBRIDO' TO 'BOTH'"
    )