import sqlalchemy as sa
from alembic import op


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_requests", sa.Column("model_cost_usd", sa.Numeric(18, 9)))
    op.create_index("ix_support_requests_closed_at", "support_requests", ["closed_at"])


def downgrade() -> None:
    op.drop_index("ix_support_requests_closed_at", table_name="support_requests")
    op.drop_column("support_requests", "model_cost_usd")
