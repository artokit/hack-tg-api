import sqlalchemy as sa
from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("rag_jobs", "data")


def downgrade() -> None:
    op.add_column("rag_jobs", sa.Column("data", sa.LargeBinary()))
