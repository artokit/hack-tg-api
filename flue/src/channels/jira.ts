import { timingSafeEqual } from 'node:crypto';
import { createChannelRouter } from '@flue/runtime';
import { Hono, type Handler } from 'hono';
import { bodyLimit } from 'hono/body-limit';
import * as v from 'valibot';

import { jiraComment, type JiraStore } from '../jira-store.js';

export function createJiraChannel(store: JiraStore): Hono {
  const webhook: Handler = async (c) => {
    const secret = process.env.BOT_API_TOKEN?.trim();
    if (!secret) return c.json({ detail: 'Jira webhook unavailable' }, 503);
    const expected = Buffer.from(secret);
    const provided = Buffer.from(c.req.header('X-Webhook-Secret') ?? '');
    if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
      return c.json({ detail: 'Invalid webhook secret' }, 401);
    }
    const input: unknown = await c.req.json().catch(() => undefined);
    const parsed = v.safeParse(jiraComment, input);
    if (!parsed.success) return c.json({ detail: 'Invalid or non-public Jira comment' }, 400);
    try {
      const created = await store.enqueue(parsed.output);
      return c.json({ status: created ? 'queued' : 'duplicate' }, 202);
    } catch (error) {
      console.warn('Jira webhook enqueue failed', error instanceof Error ? error.name : 'Error');
      return c.json({ detail: 'Jira comment processing unavailable' }, 503);
    }
  };

  return new Hono()
    .use('/webhook', bodyLimit({
      maxSize: 256 * 1024,
      onError: (c) => c.json({ detail: 'Jira event too large' }, 413),
    }))
    .route('/', createChannelRouter([{ method: 'POST', path: '/webhook', handler: webhook }]));
}
