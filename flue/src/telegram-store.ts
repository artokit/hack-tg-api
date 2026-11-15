import type { StateSession } from '@kalutskii/grammy-fsm';
import type { Pool } from 'pg';
import type { SupportAction } from './keyboards/support.js';
import type { TelegramAttachment } from './telegram-attachments.js';
import type { RequestPhase } from './telegram-requests.js';

export interface IncomingMessage {
  text: string;
  userId: number;
  firstName?: string | null;
  lastName?: string | null;
  username?: string | null;
  supportAction?: SupportAction;
  attachment?: TelegramAttachment;
}

export interface PendingUpdate {
  sequence: string;
  update_id: string;
  chat_id: string;
  payload: IncomingMessage;
  instance_id: string | null;
  submission_id: string | null;
  command_answer: string | null;
  request_id: string | null;
  request_phase: RequestPhase | null;
  received_at: Date;
}

export type DeliveryKind = 'answer' | 'fallback' | 'service';
export type DeliveryStatus = 'sent' | 'failed' | 'unknown';

export interface DeliveryReceipt {
  status: 'sending' | DeliveryStatus;
  sent_at: Date | null;
}

export class TelegramStore {
  constructor(private readonly pool: Pool, private readonly botId: string) {}

  async enqueue(updateId: number, chatId: number, message: IncomingMessage): Promise<void> {
    await this.pool.query(`
      INSERT INTO bars_telegram_updates (bot_id, update_id, chat_id, payload, received_at)
      VALUES ($1, $2, $3, $4, $5) ON CONFLICT (bot_id, update_id) DO NOTHING
    `, [this.botId, updateId, chatId, message, new Date()]);
  }

  async pending(): Promise<PendingUpdate[]> {
    const result = await this.pool.query<PendingUpdate>(`
      SELECT sequence, update_id, chat_id, payload, instance_id, submission_id, command_answer,
        request_id, request_phase, coalesce(received_at, clock_timestamp()) AS received_at
      FROM bars_telegram_updates WHERE bot_id = $1 AND finished_at IS NULL ORDER BY sequence
    `, [this.botId]);
    return result.rows;
  }

  async startProcessing(sequence: string): Promise<void> {
    await this.pool.query(`
      UPDATE bars_telegram_updates SET processing_at = clock_timestamp()
      WHERE sequence = $1 AND received_at IS NOT NULL AND processing_at IS NULL
    `, [sequence]);
  }

  async replyTiming(submissionId: string): Promise<{ received_at: Date | null; processing_at: Date | null } | undefined> {
    const result = await this.pool.query<{ received_at: Date | null; processing_at: Date | null }>(`
      SELECT received_at, processing_at FROM bars_telegram_updates
      WHERE bot_id = $1 AND submission_id = $2 ORDER BY sequence LIMIT 1
    `, [this.botId, submissionId]);
    return result.rows[0];
  }

  async recordSubmission(sequence: string, id: string): Promise<void> {
    await this.pool.query(
      'UPDATE bars_telegram_updates SET submission_id = $2 WHERE sequence = $1',
      [sequence, id],
    );
  }

  async session(chatId: string): Promise<StateSession> {
    const result = await this.pool.query<{ state: StateSession['_state'] }>(
      'SELECT state FROM bars_telegram_sessions WHERE bot_id = $1 AND chat_id = $2',
      [this.botId, chatId],
    );
    return { _state: result.rows[0]?.state ?? null };
  }

  async commandAnswer(update: PendingUpdate, text: string, session: StateSession): Promise<string> {
    await this.pool.query(
      `WITH saved AS (
        UPDATE bars_telegram_updates SET command_answer = $2 WHERE sequence = $1
        RETURNING bot_id, chat_id
      )
      INSERT INTO bars_telegram_sessions (bot_id, chat_id, state)
      SELECT bot_id, chat_id, $3::jsonb FROM saved
      ON CONFLICT (bot_id, chat_id) DO UPDATE SET state = EXCLUDED.state`,
      [update.sequence, text, session._state],
    );
    return text;
  }

  async saveSession(chatId: string, session: StateSession): Promise<void> {
    await this.pool.query(
      `INSERT INTO bars_telegram_sessions (bot_id, chat_id, state)
      VALUES ($1, $2, $3) ON CONFLICT (bot_id, chat_id) DO UPDATE SET state = EXCLUDED.state`,
      [this.botId, chatId, session._state],
    );
  }

  async finish(sequence: string): Promise<void> {
    await this.pool.query(`
      UPDATE bars_telegram_updates
      SET finished_at = now(), payload = '{}'::jsonb, command_answer = NULL
      WHERE sequence = $1
    `, [sequence]);
  }

  async recoverDeliveries(): Promise<DeliveryKind[]> {
    const result = await this.pool.query<{ kind: DeliveryKind }>(`
      UPDATE bars_telegram_deliveries SET status = 'unknown'
      WHERE bot_id = $1 AND status = 'sending'
      RETURNING COALESCE(kind, CASE
        WHEN delivery_id LIKE 'command:%' THEN 'service'
        WHEN delivery_id LIKE 'failure:%' THEN 'fallback'
        ELSE 'answer'
      END) AS kind
    `, [this.botId]);
    if (result.rowCount) console.warn('Telegram deliveries interrupted during send', result.rowCount);
    return result.rows.map((row) => row.kind);
  }

  async claimDelivery(id: string, kind: DeliveryKind): Promise<boolean> {
    const result = await this.pool.query(`
      INSERT INTO bars_telegram_deliveries (bot_id, delivery_id, status, kind)
      VALUES ($1, $2, 'sending', $3) ON CONFLICT (bot_id, delivery_id) DO NOTHING
    `, [this.botId, id, kind]);
    return result.rowCount === 1;
  }

  async delivery(id: string): Promise<DeliveryReceipt> {
    const result = await this.pool.query<DeliveryReceipt>(`
      SELECT status, sent_at FROM bars_telegram_deliveries WHERE bot_id = $1 AND delivery_id = $2
    `, [this.botId, id]);
    return result.rows[0];
  }

  async recordDelivery(id: string, status: DeliveryStatus): Promise<DeliveryReceipt> {
    const result = await this.pool.query<DeliveryReceipt>(`
      UPDATE bars_telegram_deliveries SET status = $3,
        sent_at = CASE WHEN $3 = 'sent' THEN clock_timestamp() END
      WHERE bot_id = $1 AND delivery_id = $2 RETURNING status, sent_at
    `, [this.botId, id, status]);
    return result.rows[0];
  }
}
