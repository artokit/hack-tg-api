import sqlalchemy as sa
from alembic import op


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invites", sa.Column("expires_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("invites", "expires_at")
