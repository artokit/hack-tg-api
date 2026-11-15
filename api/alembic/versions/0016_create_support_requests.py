import sqlalchemy as sa
from alembic import op


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("instance_id", sa.Text(), unique=True, nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.String(100)),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_resolved", sa.Boolean()),
        sa.Column("close_reason", sa.String(40), nullable=False),
    )
    op.add_column("tickets", sa.Column("support_request_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_tickets_support_request", "tickets", "support_requests", ["support_request_id"], ["id"],
    )
    op.create_unique_constraint("uq_tickets_support_request", "tickets", ["support_request_id"])
    op.add_column("tickets", sa.Column("attachment_comment_id", sa.String(100)))
    op.add_column("tickets", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("tickets", "next_attempt_at")
    op.drop_column("tickets", "attachment_comment_id")
    op.drop_constraint("uq_tickets_support_request", "tickets", type_="unique")
    op.drop_constraint("fk_tickets_support_request", "tickets", type_="foreignkey")
    op.drop_column("tickets", "support_request_id")
    op.drop_table("support_requests")
