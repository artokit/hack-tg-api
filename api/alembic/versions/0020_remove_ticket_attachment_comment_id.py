from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("tickets", "attachment_comment_id")


def downgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("attachment_comment_id", sa.String(100), nullable=True),
    )
