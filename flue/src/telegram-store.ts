import { randomUUID } from 'node:crypto';

import type { Pool } from 'pg';

export interface IncomingMessage {
  text: string;
  userId: number;
  firstName: string;
  lastName?: string;
  username?: string;
  commandFor?: string;
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
      INSERT INTO bars_telegram_updates (bot_id, update_id, chat_id, payload)
      VALUES ($1, $2, $3, $4) ON CONFLICT (bot_id, update_id) DO NOTHING
    `, [this.botId, updateId, chatId, message]);
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

  async commandAnswer(sequence: string, text: string): Promise<string> {
    await this.pool.query(
      'UPDATE bars_telegram_updates SET command_answer = $2 WHERE sequence = $1',
      [sequence, text],
    );
    return text;
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

  async claimDelivery(id: string): Promise<boolean> {
    const result = await this.pool.query(`
      INSERT INTO bars_telegram_deliveries (bot_id, delivery_id, status)
      VALUES ($1, $2, 'sending') ON CONFLICT (bot_id, delivery_id) DO NOTHING
    `, [this.botId, id]);
    return result.rowCount === 1;
  }

  async recordDelivery(id: string, status: 'sent' | 'failed' | 'unknown'): Promise<void> {
    await this.pool.query(`
      UPDATE bars_telegram_deliveries SET status = $3 WHERE bot_id = $1 AND delivery_id = $2
    `, [this.botId, id, status]);
  }
}
