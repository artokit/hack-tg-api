import sqlalchemy as sa
from alembic import op


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_documents", sa.Column("source_revision", sa.Text()))
    op.add_column("rag_documents", sa.Column("chunk_count", sa.Integer()))
    op.execute("""
        UPDATE rag_documents AS document
        SET source_revision = job.source_revision, chunk_count = job.chunk_count
        FROM rag_jobs AS job
        WHERE job.index_key = document.index_key AND job.source_id = document.source_id
          AND job.version = document.active_version AND job.status = 'succeeded'
    """)
    op.execute("""
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY index_key, source_id ORDER BY created_at DESC, id DESC
            ) AS position
            FROM rag_jobs
            WHERE source_kind IN ('github', 'confluence') AND status NOT IN ('deleting', 'skipped')
        )
        UPDATE rag_jobs AS job
        SET status = 'failed', error_code = 'superseded', updated_at = now()
        FROM ranked
        WHERE ranked.id = job.id AND ranked.position > 1 AND job.status IN ('queued', 'running')
    """)


def downgrade() -> None:
    op.drop_column("rag_documents", "chunk_count")
    op.drop_column("rag_documents", "source_revision")
