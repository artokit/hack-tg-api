"""create users table

Revision ID: 0001
Revises:
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_table("users")
