import type { StateSession } from '@kalutskii/grammy-fsm';
import type { Pool } from 'pg';
import type { SupportAction } from './keyboards/support.js';
import type { TelegramAttachment } from './telegram-attachments.js';
import type { RequestPhase } from './telegram-requests.js';
import { spamFingerprint } from './telegram-spam.js';

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
  spam_fingerprint: string | null;
  spam_ban_requested_at: Date | null;
  spam_ban_expires_at: Date | null;
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
    const { text, attachment, supportAction } = message;
    const fingerprint = text && !attachment && !supportAction && !text.startsWith('/') ? spamFingerprint(text) : null;
    await this.pool.query(`
      INSERT INTO bars_telegram_updates (bot_id, update_id, chat_id, payload, received_at, spam_fingerprint)
      VALUES ($1, $2, $3, $4, clock_timestamp(), $5) ON CONFLICT (bot_id, update_id) DO NOTHING
    `, [this.botId, updateId, chatId, message, fingerprint]);
  }

  async pending(): Promise<PendingUpdate[]> {
    const result = await this.pool.query<PendingUpdate>(`
      SELECT sequence, update_id, chat_id, payload, instance_id, submission_id, command_answer,
        request_id, request_phase, coalesce(received_at, clock_timestamp()) AS received_at,
        spam_fingerprint, spam_ban_requested_at, spam_ban_expires_at
      FROM bars_telegram_updates WHERE bot_id = $1 AND finished_at IS NULL ORDER BY sequence
    `, [this.botId]);
    return result.rows;
  }

  async wasSpamBlocked(update: PendingUpdate): Promise<boolean> {
    const result = await this.pool.query(`
      SELECT 1 FROM bars_telegram_sessions
      WHERE bot_id = $1 AND chat_id = $2 AND spam_blocked_until > $3
    `, [this.botId, update.chat_id, update.received_at]);
    return result.rowCount === 1;
  }

  async evaluateSpam(update: PendingUpdate, reported = false): Promise<boolean> {
    const result = await this.pool.query(`
      WITH target AS (
        SELECT incoming.sequence, incoming.received_at, split_part(incoming.spam_fingerprint, ':', 1) AS exact_key,
          nullif(split_part(incoming.spam_fingerprint, ':', 2), '') AS repeated_letter_key,
          incoming.spam_reported OR $4 AS reported
        FROM bars_telegram_updates AS incoming
        WHERE incoming.bot_id = $1 AND incoming.chat_id = $2 AND incoming.sequence = $3
          AND incoming.spam_fingerprint IS NOT NULL
          AND incoming.received_at > statement_timestamp() - interval '60 seconds'
          AND NOT EXISTS (
            SELECT 1 FROM bars_telegram_sessions AS session
            WHERE session.bot_id = $1 AND session.chat_id = $2 AND session.spam_blocked_until > incoming.received_at
          )
      ), recent AS (
        SELECT incoming.received_at, split_part(incoming.spam_fingerprint, ':', 1) AS exact_key,
          nullif(split_part(incoming.spam_fingerprint, ':', 2), '') AS repeated_letter_key,
          incoming.spam_reported OR (incoming.sequence = target.sequence AND $4) AS reported
        FROM bars_telegram_updates AS incoming CROSS JOIN target
        WHERE incoming.bot_id = $1 AND incoming.chat_id = $2 AND incoming.spam_fingerprint IS NOT NULL
          AND incoming.received_at > statement_timestamp() - interval '60 seconds'
          AND incoming.received_at >= coalesce((
            SELECT spam_blocked_until FROM bars_telegram_sessions WHERE bot_id = $1 AND chat_id = $2
          ), '-infinity'::timestamptz)
      ), burst AS (
        SELECT received_at, count(*) OVER window_10s AS messages,
          count(*) FILTER (WHERE reported) OVER window_10s AS reports
        FROM recent
        WINDOW window_10s AS (ORDER BY received_at RANGE BETWEEN interval '10 seconds' PRECEDING AND CURRENT ROW)
      ), repeated_letters AS (
        SELECT recent.received_at, count(*) OVER window_15s AS messages,
          bool_or(recent.reported) OVER window_15s AS reported
        FROM recent CROSS JOIN target WHERE recent.repeated_letter_key = target.repeated_letter_key
        WINDOW window_15s AS (ORDER BY recent.received_at RANGE BETWEEN interval '15 seconds' PRECEDING AND CURRENT ROW)
      ), decision AS (
        SELECT sequence, reported, EXISTS (
          SELECT 1 FROM recent WHERE exact_key = target.exact_key
          HAVING count(*) >= 5 AND count(*) FILTER (WHERE reported) >= 2
        ) OR EXISTS (
          SELECT 1 FROM burst WHERE messages >= 30 AND reports >= 2
            AND received_at BETWEEN target.received_at AND target.received_at + interval '10 seconds'
        ) OR EXISTS (
          SELECT 1 FROM repeated_letters WHERE messages >= 8 AND reported
            AND received_at BETWEEN target.received_at AND target.received_at + interval '15 seconds'
        ) AS should_ban FROM target
      )
      UPDATE bars_telegram_updates AS incoming SET spam_reported = decision.reported,
        spam_ban_requested_at = CASE WHEN decision.should_ban
          THEN coalesce(incoming.spam_ban_requested_at, clock_timestamp()) ELSE incoming.spam_ban_requested_at END
      FROM decision WHERE incoming.sequence = decision.sequence AND ($4 OR decision.should_ban)
      RETURNING decision.should_ban
    `, [this.botId, update.chat_id, update.sequence, reported]);
    return result.rows[0]?.should_ban === true;
  }

  async recordSpamBan(update: PendingUpdate, expiresAt: Date): Promise<void> {
    await this.pool.query(`
      WITH banned AS (
        UPDATE bars_telegram_updates SET spam_ban_expires_at = $4
        WHERE bot_id = $1 AND chat_id = $2 AND sequence = $3
        RETURNING bot_id, chat_id, spam_ban_expires_at
      )
      INSERT INTO bars_telegram_sessions (bot_id, chat_id, spam_blocked_until)
      SELECT bot_id, chat_id, spam_ban_expires_at FROM banned
      ON CONFLICT (bot_id, chat_id) DO UPDATE
      SET spam_blocked_until = greatest(bars_telegram_sessions.spam_blocked_until, EXCLUDED.spam_blocked_until)
    `, [this.botId, update.chat_id, update.sequence, expiresAt]);
  }

  async pruneSpamEvidence(): Promise<number> {
    const result = await this.pool.query(`
      UPDATE bars_telegram_updates SET spam_fingerprint = NULL, spam_reported = false
      WHERE sequence IN (
        SELECT sequence FROM bars_telegram_updates
        WHERE bot_id = $1 AND spam_fingerprint IS NOT NULL AND received_at <= clock_timestamp() - interval '60 seconds'
        LIMIT 2000
      )
    `, [this.botId]);
    return result.rowCount ?? 0;
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
