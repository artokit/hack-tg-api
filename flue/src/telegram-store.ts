import { randomUUID } from 'node:crypto';

import type { StateSession } from '@kalutskii/grammy-fsm';
import type { Pool } from 'pg';

export interface IncomingMessage {
  text: string;
  userId: number;
  firstName?: string | null;
  lastName?: string | null;
  username?: string | null;
  callback?: { id: string; data: 'end_ask'; messageId: number };
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

export interface PendingUpdate {
  sequence: string;
  update_id: string;
  chat_id: string;
  payload: IncomingMessage;
  instance_id: string | null;
  submission_id: string | null;
  command_answer: string | null;
}

export class TelegramStore {
  constructor(private readonly pool: Pool, private readonly botId: string) {}

  async enqueue(updateId: number, chatId: number, message: IncomingMessage): Promise<void> {
    await this.pool.query(`
      WITH incoming AS (
        INSERT INTO bars_telegram_updates (bot_id, update_id, chat_id, payload)
        VALUES ($1, $2, $3, $4) ON CONFLICT (bot_id, update_id) DO NOTHING
        RETURNING sequence
      )
      INSERT INTO bars_telegram_messages (
        bot_id, chat_id, message_key, update_sequence, role, text, starts_dialog
      )
      SELECT $1, $3, $5, sequence, 'user', $6, $7 FROM incoming WHERE $8
    `, [
      this.botId, updateId, chatId, message, `user:${updateId}`, message.text,
      /^\/start(?:@[A-Za-z0-9_]+)?(?:\s|$)/i.test(message.text), !message.callback,
    ]);
  }

  async hasEarlierPending(update: PendingUpdate): Promise<boolean> {
    const result = await this.pool.query(`
      SELECT 1 FROM bars_telegram_updates
      WHERE bot_id = $1 AND chat_id = $2 AND sequence < $3 AND finished_at IS NULL LIMIT 1
    `, [this.botId, update.chat_id, update.sequence]);
    return result.rows.length > 0;
  }

  async history(update: PendingUpdate): Promise<ChatMessage[]> {
    const result = await this.pool.query<ChatMessage>(`
      WITH boundary AS (
        SELECT update_sequence FROM bars_telegram_messages
        WHERE bot_id = $1 AND chat_id = $2 AND starts_dialog AND update_sequence < $3
        ORDER BY update_sequence DESC LIMIT 1
      )
      SELECT role, text FROM bars_telegram_messages
      WHERE bot_id = $1 AND chat_id = $2
        AND update_sequence >= COALESCE((SELECT update_sequence FROM boundary), 0)
        AND update_sequence < $3
      ORDER BY sequence
    `, [this.botId, update.chat_id, update.sequence]);
    return result.rows;
  }

  async pending(): Promise<PendingUpdate[]> {
    const result = await this.pool.query<PendingUpdate>(`
      SELECT sequence, update_id, chat_id, payload, instance_id, submission_id, command_answer
      FROM bars_telegram_updates WHERE bot_id = $1 AND finished_at IS NULL ORDER BY sequence
    `, [this.botId]);
    return result.rows;
  }

  async pinInstance(update: PendingUpdate, initialId: string): Promise<string> {
    if (update.instance_id !== null) return update.instance_id;
    const result = await this.pool.query<{ instance_id: string }>(`
      WITH dialog AS (
        INSERT INTO bars_telegram_dialogs (bot_id, chat_id, instance_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (bot_id, chat_id) DO UPDATE SET chat_id = EXCLUDED.chat_id
        RETURNING instance_id
      )
      UPDATE bars_telegram_updates SET instance_id = dialog.instance_id
      FROM dialog WHERE sequence = $4 RETURNING bars_telegram_updates.instance_id
    `, [this.botId, update.chat_id, initialId, update.sequence]);
    return result.rows[0].instance_id;
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

  async reset(update: PendingUpdate, initialId: string): Promise<string> {
    const result = await this.pool.query<{ command_answer: string }>(`
      WITH reset_command AS (
        UPDATE bars_telegram_updates AS current
        SET command_answer = CASE WHEN EXISTS (
          SELECT 1 FROM bars_telegram_updates AS previous
          WHERE previous.bot_id = current.bot_id AND previous.chat_id = current.chat_id
            AND previous.finished_at IS NULL AND previous.submission_id IS NOT NULL
        ) THEN 'Я ещё отвечаю на предыдущий вопрос. Попробуй чуть позже.'
          ELSE 'Диалог сброшен. Можешь написать новый вопрос.'
        END
        WHERE current.sequence = $4 AND current.command_answer IS NULL
        RETURNING command_answer
      ), dialog AS (
        INSERT INTO bars_telegram_dialogs (bot_id, chat_id, instance_id)
        SELECT $1, $2, $3 FROM reset_command
        WHERE command_answer = 'Диалог сброшен. Можешь написать новый вопрос.'
        ON CONFLICT (bot_id, chat_id) DO UPDATE SET instance_id = EXCLUDED.instance_id
        RETURNING chat_id
      ), cleared AS (
        DELETE FROM bars_telegram_sessions
        WHERE bot_id = $1 AND chat_id = $2
          AND EXISTS (SELECT 1 FROM dialog)
      )
      SELECT command_answer FROM reset_command
    `, [this.botId, update.chat_id, `${initialId}:${randomUUID()}`, update.sequence]);
    return result.rows[0].command_answer;
  }

  async finish(sequence: string): Promise<void> {
    await this.pool.query(`
      UPDATE bars_telegram_updates
      SET finished_at = now(), payload = '{}'::jsonb, command_answer = NULL
      WHERE sequence = $1
    `, [sequence]);
  }

  async recoverDeliveries(): Promise<void> {
    const result = await this.pool.query(`
      UPDATE bars_telegram_deliveries SET status = 'unknown'
      WHERE bot_id = $1 AND status = 'sending'
    `, [this.botId]);
    if (result.rowCount) console.warn('Telegram deliveries interrupted during send', result.rowCount);
  }

  async claimDelivery(
    id: string, chatId: string, text: string, updateSequence: string | null, historyExport: boolean,
  ): Promise<boolean> {
    const result = await this.pool.query(`
      INSERT INTO bars_telegram_deliveries (
        bot_id, delivery_id, status, chat_id, text, update_sequence, history_export
      )
      VALUES ($1, $2, 'sending', $3, $4, $5, $6) ON CONFLICT (bot_id, delivery_id) DO NOTHING
    `, [this.botId, id, chatId, text, updateSequence, historyExport]);
    return result.rowCount === 1;
  }

  async recordDelivery(id: string, status: 'sent' | 'failed' | 'unknown'): Promise<void> {
    await this.pool.query(`
      WITH delivered AS (
        UPDATE bars_telegram_deliveries SET status = $3 WHERE bot_id = $1 AND delivery_id = $2
        RETURNING chat_id, text, update_sequence, history_export
      )
      INSERT INTO bars_telegram_messages (bot_id, chat_id, message_key, update_sequence, role, text)
      SELECT $1, chat_id, $2, update_sequence, 'assistant', text FROM delivered
      WHERE $3 = 'sent' AND NOT history_export AND update_sequence IS NOT NULL
      ON CONFLICT (bot_id, message_key) DO NOTHING
    `, [this.botId, id, status]);
  }
}
