from alembic import op


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.bars_telegram_requests') IS NOT NULL THEN
                ALTER TABLE public.bars_telegram_requests
                    ADD COLUMN IF NOT EXISTS kb_search_count integer CHECK (kb_search_count >= 0);
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.bars_telegram_requests') IS NOT NULL THEN
                ALTER TABLE public.bars_telegram_requests DROP COLUMN kb_search_count;
            END IF;
        END
        $$
    """)
