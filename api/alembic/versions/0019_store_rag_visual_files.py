import sqlalchemy as sa
from alembic import op


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_visual_files",
        sa.Column("file_id", sa.Uuid(), primary_key=True),
        sa.Column("index_key", sa.String(64), nullable=False),
        sa.Column("version", sa.String(36), nullable=False),
    )
    op.create_index("ix_rag_visual_files_version", "rag_visual_files", ["index_key", "version"])


def downgrade() -> None:
    op.drop_index("ix_rag_visual_files_version", table_name="rag_visual_files")
    op.drop_table("rag_visual_files")
