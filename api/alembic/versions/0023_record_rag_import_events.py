import sqlalchemy as sa
from alembic import op


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_import_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column("format", sa.String(4)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("processing_ms", sa.Float()),
        sa.Column("excluded", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("rag_jobs", sa.Column("import_event_id", sa.Uuid()))
    op.create_foreign_key("fk_rag_jobs_import_event_id", "rag_jobs", "rag_import_events", ["import_event_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_rag_jobs_import_event_id", "rag_jobs", type_="foreignkey")
    op.drop_column("rag_jobs", "import_event_id")
    op.drop_table("rag_import_events")
