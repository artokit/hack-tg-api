from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS aw_mock.samples")
    op.execute("DROP TABLE IF EXISTS public.aw_mock_samples")
    op.execute("DROP SCHEMA IF EXISTS aw_mock")


def downgrade() -> None:
    op.execute("CREATE SCHEMA aw_mock")
    op.create_table(
        "aw_mock_samples",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("series", sa.String(50), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        schema="public",
    )
    op.create_index(
        "ix_aw_mock_samples_recorded_at", "aw_mock_samples", ["recorded_at"], schema="public"
    )
    op.execute(
        "CREATE VIEW aw_mock.samples AS "
        "SELECT id, recorded_at, series, value, true AS is_mock "
        "FROM public.aw_mock_samples"
    )
