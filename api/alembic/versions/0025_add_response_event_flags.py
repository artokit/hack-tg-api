from typing import Sequence, Union

from alembic import op


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.bars_telegram_requests') IS NOT NULL THEN
                ALTER TABLE public.bars_telegram_requests
                    ADD COLUMN IF NOT EXISTS tracks_response_metrics boolean NOT NULL DEFAULT false;
            END IF;
            IF to_regclass('public.bars_telegram_request_events') IS NOT NULL THEN
                ALTER TABLE public.bars_telegram_request_events
                    ADD COLUMN IF NOT EXISTS has_answer boolean,
                    ADD COLUMN IF NOT EXISTS has_clarification boolean;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.bars_telegram_request_events') IS NOT NULL THEN
                ALTER TABLE public.bars_telegram_request_events
                    DROP COLUMN has_clarification,
                    DROP COLUMN has_answer;
            END IF;
            IF to_regclass('public.bars_telegram_requests') IS NOT NULL THEN
                ALTER TABLE public.bars_telegram_requests
                    DROP COLUMN tracks_response_metrics;
            END IF;
        END
        $$
    """)
