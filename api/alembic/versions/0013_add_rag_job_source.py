import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_jobs", sa.Column("source_kind", sa.String(32)))
    op.add_column("rag_jobs", sa.Column("source_locator", JSONB()))
    op.add_column("rag_jobs", sa.Column("source_revision", sa.Text()))


def downgrade() -> None:
    op.execute("DELETE FROM rag_jobs WHERE status = 'skipped' AND source_kind IS NOT NULL")
    op.execute(
        "UPDATE rag_jobs SET status = 'failed', error_code = 'source_unavailable' "
        "WHERE status IN ('queued', 'running') AND source_kind IS NOT NULL"
    )
    op.drop_column("rag_jobs", "source_revision")
    op.drop_column("rag_jobs", "source_locator")
    op.drop_column("rag_jobs", "source_kind")
