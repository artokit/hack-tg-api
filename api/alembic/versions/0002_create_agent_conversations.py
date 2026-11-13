"""Create agent conversations."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column(
            "telegram_user_id", sa.BigInteger(), primary_key=True, autoincrement=False
        ),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_conversations")
