import sqlalchemy as sa
from alembic import op


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_import_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("index_key", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("version", sa.String(36)),
        sa.Column("file_id", sa.Uuid()),
        sa.Column("upload_job_id", sa.Uuid()),
        sa.Column("delete_original", sa.Boolean(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_rag_import_artifacts_source", "rag_import_artifacts", ["index_key", "source_id"])


def downgrade() -> None:
    op.drop_table("rag_import_artifacts")
