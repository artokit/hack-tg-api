import type { Pool } from 'pg';
import * as v from 'valibot';

const id = v.pipe(v.string(), v.regex(/^[1-9][0-9]{0,19}$/));
export const jiraComment = v.object({
  event: v.literal('jira.comment.created'),
  issue_key: v.pipe(v.string(), v.maxLength(100), v.regex(/^[A-Z][A-Z0-9_]*-[1-9][0-9]*$/)),
  issue_id: id,
  comment_id: id,
  comment: v.pipe(v.string(), v.minLength(1), v.maxLength(32768)),
  author: v.pipe(v.string(), v.maxLength(255)),
  internal: v.literal(false),
});

export type JiraComment = v.InferOutput<typeof jiraComment>;
export type JiraStatus = 'sent' | 'failed' | 'unknown' | 'ignored';

export interface PendingJiraComment {
  issue_id: string;
  comment_id: string;
  payload: JiraComment;
  attempts: number;
}

export class JiraStore {
  constructor(private readonly pool: Pool, private readonly botId: string) {}

  async enqueue(event: JiraComment): Promise<boolean> {
    const result = await this.pool.query(`
      INSERT INTO bars_jira_comments (bot_id, issue_id, comment_id, payload)
      VALUES ($1, $2, $3, $4) ON CONFLICT (bot_id, issue_id, comment_id) DO NOTHING
    `, [this.botId, event.issue_id, event.comment_id, event]);
    return result.rowCount === 1;
  }

  async claim(): Promise<PendingJiraComment | undefined> {
    const result = await this.pool.query<PendingJiraComment>(`
      WITH pending AS (
        SELECT bot_id, issue_id, comment_id FROM bars_jira_comments
        WHERE bot_id = $1 AND status = 'queued' AND next_attempt_at <= clock_timestamp()
        ORDER BY received_at, comment_id LIMIT 1 FOR UPDATE SKIP LOCKED
      )
      UPDATE bars_jira_comments AS comment
      SET next_attempt_at = clock_timestamp() + interval '5 minutes', attempts = attempts + 1
      FROM pending
      WHERE comment.bot_id = pending.bot_id AND comment.issue_id = pending.issue_id
        AND comment.comment_id = pending.comment_id
      RETURNING comment.issue_id, comment.comment_id, comment.payload, comment.attempts
    `, [this.botId]);
    return result.rows[0];
  }

  async retry(event: PendingJiraComment): Promise<void> {
    await this.pool.query(`
      UPDATE bars_jira_comments SET next_attempt_at = clock_timestamp() + $4 * interval '1 second'
      WHERE bot_id = $1 AND issue_id = $2 AND comment_id = $3 AND status = 'queued'
    `, [this.botId, event.issue_id, event.comment_id, Math.min(300, 5 * 2 ** Math.min(event.attempts, 6))]);
  }

  async finish(event: PendingJiraComment, status: JiraStatus): Promise<void> {
    await this.pool.query(`
      UPDATE bars_jira_comments SET status = $4, finished_at = clock_timestamp(), payload = NULL
      WHERE bot_id = $1 AND issue_id = $2 AND comment_id = $3
    `, [this.botId, event.issue_id, event.comment_id, status]);
  }
}
