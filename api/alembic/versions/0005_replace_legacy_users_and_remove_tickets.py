from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("ticket_messages")
    op.drop_table("tickets")
    op.drop_table("users")
    op.rename_table("admins", "users")
    op.execute("ALTER INDEX ix_admins_email RENAME TO ix_users_email")
    op.execute("ALTER TABLE users RENAME CONSTRAINT admins_pkey TO users_pkey")


def downgrade() -> None:
    op.execute("ALTER TABLE users RENAME CONSTRAINT users_pkey TO admins_pkey")
    op.execute("ALTER INDEX ix_users_email RENAME TO ix_admins_email")
    op.rename_table("users", "admins")
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=True)
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("taken_by_username", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tickets_group_id", "tickets", ["group_id"], unique=True)
    op.create_index("ix_tickets_user_id", "tickets", ["user_id"])
    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("sender", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_ticket_messages_ticket_id", "ticket_messages", ["ticket_id"])
