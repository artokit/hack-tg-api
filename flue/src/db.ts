import { postgres } from '@flue/postgres';
import type { AgentSubmissionStore } from '@flue/runtime/adapter';
import pg from 'pg';

import { required } from './config.js';

export const pool = new pg.Pool({
  connectionString: required('FLUE_DATABASE_URL'),
  connectionTimeoutMillis: 5_000,
});
pool.on('error', (error) => console.error('PostgreSQL idle connection error', error.name));

const adapter = postgres({
  query: async (sql, params) => (await pool.query(sql, params ? [...params] : undefined)).rows,
  transaction: async (run) => {
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      const result = await run({
        query: async (sql, params) => (await client.query(sql, params ? [...params] : undefined)).rows,
      });
      await client.query('COMMIT');
      return result;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  },
  close: () => pool.end(),
});

let submissions: AgentSubmissionStore;

export async function responseSubmission(id: string): Promise<string> {
  const submission = await submissions.getSubmission(id);
  return submission?.joinedInto ?? id;
}

export default {
  ...adapter,
  async connect() {
    const stores = await adapter.connect();
    submissions = stores.submissionStore;
    return stores;
  },
  async migrate() {
    await adapter.migrate?.();
    await pool.query(`
      CREATE TABLE IF NOT EXISTS bars_telegram_updates (
        sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        bot_id text NOT NULL,
        update_id bigint NOT NULL,
        chat_id bigint NOT NULL,
        payload jsonb NOT NULL,
        instance_id text,
        submission_id text,
        command_answer text,
        finished_at timestamptz,
        UNIQUE (bot_id, update_id)
      );
      CREATE INDEX IF NOT EXISTS bars_telegram_pending_updates
        ON bars_telegram_updates (bot_id, sequence) WHERE finished_at IS NULL;

      CREATE TABLE IF NOT EXISTS bars_telegram_dialogs (
        bot_id text NOT NULL,
        chat_id bigint NOT NULL,
        instance_id text NOT NULL,
        PRIMARY KEY (bot_id, chat_id)
      );

      CREATE TABLE IF NOT EXISTS bars_telegram_deliveries (
        bot_id text NOT NULL,
        delivery_id text NOT NULL,
        status text NOT NULL CHECK (status IN ('sending', 'sent', 'failed', 'unknown')),
        PRIMARY KEY (bot_id, delivery_id)
      );
    `);
  },
};
