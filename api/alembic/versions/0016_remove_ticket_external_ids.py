from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("tickets", "external_key")
    op.drop_column("tickets", "external_id")


def downgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("external_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("external_key", sa.String(100), nullable=True),
    )
