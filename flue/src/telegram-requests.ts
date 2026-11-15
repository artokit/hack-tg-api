import { randomUUID } from 'node:crypto';

import type { Pool } from 'pg';

import { type ClosedRequest, type CloseReason, type HandoffDraft, type ReplyFlags, resolution } from './support-request.js';
import type { PendingUpdate } from './telegram-store.js';

export type RequestPhase =
  'answer' | 'feedback' | 'clarification' | 'details' | 'technical' | 'handoff_confirmation' | 'close_confirmation';

export interface ActiveRequest {
  id: string;
  chat_id: string;
  instance_id: string;
  latest_sequence: string;
  phase: RequestPhase;
}

interface Finalization {
  outcome: ClosedRequest;
  finalizer_attempt: number;
}

export class TelegramRequests {
  constructor(private readonly pool: Pool, private readonly botId: string) {}

  async active(chatId: string): Promise<ActiveRequest | undefined> {
    const result = await this.pool.query<ActiveRequest>(`
      SELECT id, chat_id, instance_id, latest_sequence, phase FROM bars_telegram_requests
      WHERE bot_id = $1 AND chat_id = $2 AND closed_at IS NULL
    `, [this.botId, chatId]);
    return result.rows[0];
  }

  async pin(update: PendingUpdate, instancePrefix: string): Promise<ActiveRequest | undefined> {
    if (update.request_id) {
      const current = await this.active(update.chat_id);
      return current?.id === update.request_id
        ? { ...current, phase: update.request_phase ?? current.phase } : undefined;
    }

    const id = randomUUID();
    const result = await this.pool.query<ActiveRequest>(`
      WITH current_request AS (
        INSERT INTO bars_telegram_requests (
          id, bot_id, chat_id, instance_id, opened_at, phase, latest_sequence, tracks_model_cost,
          tracks_response_metrics, kb_search_count
        )
        VALUES ($1, $2, $3, $4, $5, 'technical', $6, true, true, 0)
        ON CONFLICT (bot_id, chat_id) WHERE closed_at IS NULL DO UPDATE
        SET latest_sequence = greatest(bars_telegram_requests.latest_sequence, EXCLUDED.latest_sequence)
        RETURNING id, chat_id, instance_id, latest_sequence, phase, phase_sent_at
      ), pinned AS (
        UPDATE bars_telegram_updates
        SET request_id = current_request.id, instance_id = current_request.instance_id,
          request_phase = CASE
            WHEN current_request.phase = 'feedback' AND received_at < current_request.phase_sent_at THEN 'answer'
            WHEN current_request.phase = 'answer' AND current_request.phase_sent_at IS NULL THEN 'technical'
            ELSE current_request.phase END
        FROM current_request WHERE sequence = $6
        RETURNING request_phase AS phase
      )
      SELECT id, chat_id, instance_id, latest_sequence, pinned.phase FROM current_request CROSS JOIN pinned
    `, [id, this.botId, update.chat_id, `${instancePrefix}:${id}`, update.received_at, update.sequence]);
    return result.rows[0];
  }

  async append(
    request: ActiveRequest, key: string, role: 'user' | 'assistant', at: Date,
    text: string | null, updateSequence?: string, flags?: ReplyFlags,
  ): Promise<void> {
    await this.pool.query(`
      INSERT INTO bars_telegram_request_events (
        request_id, event_key, role, occurred_at, text, update_sequence, has_answer, has_clarification
      )
      SELECT id, $2, $3, $4, $5, $6, $8, $9 FROM bars_telegram_requests
      WHERE id = $1 AND bot_id = $7 AND closed_at IS NULL
      ON CONFLICT (request_id, event_key) DO NOTHING
    `, [request.id, key, role, at, text, updateSequence ?? null, this.botId,
      flags?.hasAnswer ?? null, flags?.hasClarification ?? null]);
  }

  async advance(
    request: ActiveRequest, sequence: string, phase: RequestPhase, sentAt: Date,
  ): Promise<void> {
    const seconds = phase === 'answer' ? 120 : 300;
    await this.pool.query(`
      UPDATE bars_telegram_requests SET phase = $4, due_at = $5, phase_sent_at = $6
      WHERE id = $1 AND bot_id = $2 AND latest_sequence = $3 AND closed_at IS NULL
    `, [request.id, this.botId, sequence, phase, new Date(sentAt.getTime() + seconds * 1000), sentAt]);
  }

  async clearDeadline(request: ActiveRequest, sequence: string): Promise<void> {
    await this.pool.query(`
      UPDATE bars_telegram_requests SET phase = 'technical', due_at = NULL
      WHERE id = $1 AND bot_id = $2 AND latest_sequence = $3 AND closed_at IS NULL
    `, [request.id, this.botId, sequence]);
  }

  async due(requestId?: string): Promise<ActiveRequest[]> {
    const result = await this.pool.query<ActiveRequest>(`
      SELECT id, chat_id, instance_id, latest_sequence, phase FROM bars_telegram_requests AS request
      WHERE bot_id = $1 AND closed_at IS NULL AND due_at <= clock_timestamp()
        AND ($2::uuid IS NULL OR id = $2)
        AND NOT EXISTS (
          SELECT 1 FROM bars_telegram_updates AS pending
          WHERE pending.bot_id = request.bot_id AND pending.chat_id = request.chat_id
            AND pending.finished_at IS NULL
        )
      ORDER BY due_at LIMIT 20
    `, [this.botId, requestId ?? null]);
    return result.rows;
  }

  async closedBy(update: PendingUpdate): Promise<CloseReason | undefined> {
    const result = await this.pool.query<{ reason: CloseReason }>(`
      SELECT outcome->>'close_reason' AS reason FROM bars_telegram_requests
      WHERE id = $1 AND bot_id = $2 AND latest_sequence = $3 AND closed_at IS NOT NULL
    `, [update.request_id, this.botId, update.sequence]);
    return result.rows[0]?.reason;
  }

  async close(
    request: ActiveRequest, sequence: string, reason: CloseReason, handoff?: HandoffDraft, onlyIfIdle = false,
  ): Promise<boolean> {
    const result = await this.pool.query(`
      WITH closed_request AS (
        UPDATE bars_telegram_requests SET
          closed_at = closed.at, finalizer_due_at = closed.at, due_at = NULL,
          outcome = jsonb_build_object(
            'request_id', id, 'instance_id', instance_id, 'telegram_chat_id', chat_id::text,
            'category_id', NULL, 'opened_at', opened_at, 'closed_at', closed.at,
            'close_reason', $4::text, 'is_resolved', $5::boolean
          ) || $6::jsonb
        FROM (SELECT clock_timestamp() AS at) AS closed
        WHERE id = $1 AND bot_id = $2 AND latest_sequence = $3 AND closed_at IS NULL
          AND (NOT $7::boolean OR (due_at <= clock_timestamp() AND NOT EXISTS (
            SELECT 1 FROM bars_telegram_updates AS pending
            WHERE pending.bot_id = $2 AND pending.chat_id = bars_telegram_requests.chat_id AND pending.finished_at IS NULL
          )))
        RETURNING bot_id, chat_id
      ), cleared_session AS (
        UPDATE bars_telegram_sessions AS session SET state = NULL
        FROM closed_request
        WHERE session.bot_id = closed_request.bot_id AND session.chat_id = closed_request.chat_id
      )
      SELECT chat_id FROM closed_request
    `, [request.id, this.botId, sequence, reason, resolution(reason), handoff ? { handoff } : {}, onlyIfIdle]);
    return result.rowCount === 1;
  }

  async finalizations(): Promise<Finalization[]> {
    const result = await this.pool.query<Finalization>(`
      SELECT outcome, finalizer_attempt FROM bars_telegram_requests
      WHERE bot_id = $1 AND finalized_at IS NULL AND finalizer_due_at <= clock_timestamp()
      ORDER BY finalizer_due_at LIMIT 20
    `, [this.botId]);
    return result.rows;
  }

  async finalized(id: string): Promise<void> {
    await this.pool.query(`
      UPDATE bars_telegram_requests SET finalized_at = clock_timestamp()
      WHERE id = $1 AND bot_id = $2
    `, [id, this.botId]);
  }

  async retryFinalization(id: string, attemptFailed: boolean): Promise<void> {
    await this.pool.query(`
      UPDATE bars_telegram_requests SET finalizer_attempt = finalizer_attempt + $3,
        finalizer_due_at = clock_timestamp() + interval '30 seconds'
      WHERE id = $1 AND bot_id = $2 AND finalized_at IS NULL
    `, [id, this.botId, attemptFailed ? 1 : 0]);
  }
}

export async function requestHistory(pool: Pool, request: ClosedRequest) {
  const result = await pool.query<{
    role: 'user' | 'assistant'; text: string | null; submission_id: string | null; occurred_at: Date;
  }>(`
    SELECT event.role, event.text, incoming.submission_id, event.occurred_at
    FROM bars_telegram_request_events AS event
    JOIN bars_telegram_requests AS request ON request.id = event.request_id
    LEFT JOIN bars_telegram_updates AS incoming ON incoming.sequence = event.update_sequence
    WHERE request.id = $1 AND request.instance_id = $2 AND request.closed_at IS NOT NULL
    ORDER BY event.occurred_at, event.id
  `, [request.request_id, request.instance_id]);
  return result.rows;
}
