import sqlalchemy as sa
from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_jobs", sa.Column("confluence_space_id", sa.String(19)))
    op.add_column("rag_jobs", sa.Column("confluence_version", sa.BigInteger()))


def downgrade() -> None:
    op.execute("DELETE FROM rag_jobs WHERE status = 'skipped' AND confluence_space_id IS NOT NULL")
    op.execute(
        "UPDATE rag_jobs SET status = 'failed', error_code = 'confluence_disabled' "
        "WHERE status IN ('queued', 'running') AND confluence_space_id IS NOT NULL"
    )
    op.drop_column("rag_jobs", "confluence_version")
    op.drop_column("rag_jobs", "confluence_space_id")
