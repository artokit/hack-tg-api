import sqlalchemy as sa
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_documents",
        sa.Column("source_id", sa.String(100), primary_key=True),
        sa.Column("index_key", sa.String(64), primary_key=True),
        sa.Column("active_version", sa.String(36), nullable=False),
    )
    op.create_table(
        "rag_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("index_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("format", sa.String(4), nullable=False),
        sa.Column("data", sa.LargeBinary()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(32)),
        sa.Column("version", sa.String(36)),
        sa.Column("chunk_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_jobs_index_status_created", "rag_jobs", ["index_key", "status", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_table("rag_jobs")
    op.drop_table("rag_documents")
