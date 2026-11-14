import sqlalchemy as sa
from alembic import op


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_jobs", sa.Column("size_bytes", sa.Integer()))


def downgrade() -> None:
    op.drop_column("rag_jobs", "size_bytes")
