"""Remove external_id and display_key from tickets.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: str = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("tickets", "external_id")
    op.drop_column("tickets", "display_key")


def downgrade() -> None:
    op.add_column("tickets", sa.Column("external_id", sa.String(100), nullable=True))
    op.add_column("tickets", sa.Column("display_key", sa.String(100), nullable=True))
