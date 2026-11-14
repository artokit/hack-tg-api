import sqlalchemy as sa
from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_jobs", sa.Column("file_id", sa.Uuid()))


def downgrade() -> None:
    op.drop_column("rag_jobs", "file_id")
