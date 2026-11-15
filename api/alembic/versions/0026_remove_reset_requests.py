from typing import Sequence, Union

from alembic import op


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TEMP TABLE aw_reset_request_ids (id uuid PRIMARY KEY) ON COMMIT DROP")
    op.execute("""
        INSERT INTO aw_reset_request_ids
        SELECT id FROM public.support_requests WHERE close_reason = 'reset'
    """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.bars_telegram_requests') IS NOT NULL THEN
                INSERT INTO aw_reset_request_ids
                SELECT id FROM public.bars_telegram_requests
                WHERE outcome->>'close_reason' = 'reset'
                ON CONFLICT DO NOTHING;

                IF EXISTS (
                    SELECT 1 FROM public.bars_telegram_requests AS request
                    JOIN aw_reset_request_ids AS removed ON removed.id = request.id
                    WHERE request.closed_at IS NULL
                        OR request.outcome->>'close_reason' IS DISTINCT FROM 'reset'
                ) THEN
                    RAISE EXCEPTION 'Reset request conflicts with an active or different runtime outcome';
                END IF;
            END IF;

            IF EXISTS (
                SELECT 1 FROM public.support_requests AS request
                JOIN aw_reset_request_ids AS removed ON removed.id = request.id
                WHERE request.close_reason IS DISTINCT FROM 'reset'
            ) THEN
                RAISE EXCEPTION 'Reset request conflicts with a different saved outcome';
            END IF;

            IF EXISTS (
                SELECT 1 FROM public.tickets AS ticket
                JOIN aw_reset_request_ids AS removed ON removed.id = ticket.support_request_id
            ) THEN
                RAISE EXCEPTION 'Reset requests have linked tickets; review them before deleting requests';
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'bars_telegram_updates'
                    AND column_name = 'request_id'
            ) THEN
                IF EXISTS (
                    SELECT 1 FROM public.bars_telegram_updates AS incoming
                    JOIN aw_reset_request_ids AS removed ON removed.id = incoming.request_id
                    WHERE incoming.finished_at IS NULL
                ) THEN
                    RAISE EXCEPTION 'Reset requests still have pending Telegram updates';
                END IF;
                UPDATE public.bars_telegram_updates
                SET request_id = NULL, request_phase = NULL
                WHERE request_id IN (SELECT id FROM aw_reset_request_ids);
            END IF;

            IF to_regclass('public.bars_telegram_request_events') IS NOT NULL THEN
                DELETE FROM public.bars_telegram_request_events
                WHERE request_id IN (SELECT id FROM aw_reset_request_ids);
            END IF;
            IF to_regclass('public.bars_telegram_request_model_costs') IS NOT NULL THEN
                DELETE FROM public.bars_telegram_request_model_costs
                WHERE request_id IN (SELECT id FROM aw_reset_request_ids);
            END IF;

            DELETE FROM public.support_requests WHERE id IN (SELECT id FROM aw_reset_request_ids);
            IF to_regclass('public.bars_telegram_requests') IS NOT NULL THEN
                DELETE FROM public.bars_telegram_requests WHERE id IN (SELECT id FROM aw_reset_request_ids);
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    pass
