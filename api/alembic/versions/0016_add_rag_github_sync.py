from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_github_syncs",
        sa.Column("index_key", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("rag_github_syncs")
