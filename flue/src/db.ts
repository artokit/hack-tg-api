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

export async function submissionText(id: string): Promise<string | undefined> {
  return (await submissions.getSubmission(id))?.input.message.body;
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
      ALTER TABLE bars_telegram_updates ADD COLUMN IF NOT EXISTS received_at timestamptz;
      ALTER TABLE bars_telegram_updates ADD COLUMN IF NOT EXISTS processing_at timestamptz;
      CREATE INDEX IF NOT EXISTS bars_telegram_pending_updates
        ON bars_telegram_updates (bot_id, sequence) WHERE finished_at IS NULL;
      CREATE INDEX IF NOT EXISTS bars_telegram_update_submission
        ON bars_telegram_updates (bot_id, submission_id) WHERE submission_id IS NOT NULL;

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
      ALTER TABLE bars_telegram_deliveries ADD COLUMN IF NOT EXISTS kind text;

      CREATE TABLE IF NOT EXISTS bars_telegram_sessions (
        bot_id text NOT NULL,
        chat_id bigint NOT NULL,
        state jsonb,
        PRIMARY KEY (bot_id, chat_id)
      );

      ALTER TABLE bars_telegram_updates ADD COLUMN IF NOT EXISTS request_id uuid;
      ALTER TABLE bars_telegram_updates ADD COLUMN IF NOT EXISTS request_phase text;
      ALTER TABLE bars_telegram_deliveries ADD COLUMN IF NOT EXISTS sent_at timestamptz;

      CREATE TABLE IF NOT EXISTS bars_telegram_requests (
        id uuid PRIMARY KEY,
        bot_id text NOT NULL,
        chat_id bigint NOT NULL,
        instance_id text NOT NULL UNIQUE,
        opened_at timestamptz NOT NULL,
        closed_at timestamptz,
        phase text NOT NULL,
        phase_sent_at timestamptz,
        latest_sequence bigint NOT NULL,
        due_at timestamptz,
        outcome jsonb,
        finalizer_attempt integer NOT NULL DEFAULT 0,
        finalizer_due_at timestamptz,
        finalized_at timestamptz
      );

      CREATE UNIQUE INDEX IF NOT EXISTS bars_telegram_active_request
        ON bars_telegram_requests (bot_id, chat_id) WHERE closed_at IS NULL;
      CREATE INDEX IF NOT EXISTS bars_telegram_due_request
        ON bars_telegram_requests (bot_id, due_at) WHERE closed_at IS NULL AND due_at IS NOT NULL;
      CREATE INDEX IF NOT EXISTS bars_telegram_due_finalization
        ON bars_telegram_requests (bot_id, finalizer_due_at) WHERE finalized_at IS NULL AND outcome IS NOT NULL;
      CREATE INDEX IF NOT EXISTS bars_telegram_pending_chat
        ON bars_telegram_updates (bot_id, chat_id, received_at) WHERE finished_at IS NULL;

      ALTER TABLE bars_telegram_requests ADD COLUMN IF NOT EXISTS tracks_model_cost boolean NOT NULL DEFAULT false;
      CREATE TABLE IF NOT EXISTS bars_telegram_request_model_costs (
        request_id uuid NOT NULL REFERENCES bars_telegram_requests (id) ON DELETE CASCADE,
        turn_id text NOT NULL,
        occurred_at timestamptz NOT NULL,
        cost_nano_usd bigint CHECK (cost_nano_usd >= 0),
        PRIMARY KEY (request_id, turn_id)
      );

      CREATE TABLE IF NOT EXISTS bars_telegram_request_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        request_id uuid NOT NULL REFERENCES bars_telegram_requests (id),
        event_key text NOT NULL,
        role text NOT NULL CHECK (role IN ('user', 'assistant')),
        text text,
        update_sequence bigint REFERENCES bars_telegram_updates (sequence),
        occurred_at timestamptz NOT NULL,
        UNIQUE (request_id, event_key),
        CHECK (text IS NOT NULL OR update_sequence IS NOT NULL)
      );

      CREATE TABLE IF NOT EXISTS bars_jira_comments (
        bot_id text NOT NULL,
        issue_id text NOT NULL,
        comment_id text NOT NULL,
        payload jsonb,
        status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'unknown', 'ignored')),
        attempts integer NOT NULL DEFAULT 0,
        received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        finished_at timestamptz,
        PRIMARY KEY (bot_id, issue_id, comment_id)
      );
      CREATE INDEX IF NOT EXISTS bars_jira_pending_comments
        ON bars_jira_comments (bot_id, next_attempt_at) WHERE status = 'queued';
    `);
  },
};
