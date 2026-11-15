import { createHmac, timingSafeEqual } from 'node:crypto';
import { createChannelRouter } from '@flue/runtime';
import { Hono, type Handler } from 'hono';
import { bodyLimit } from 'hono/body-limit';
import * as v from 'valibot';

import { apiRequest } from '../bot-api.js';

const delivery = v.object({
  repository: v.object({ full_name: v.string() }),
  ref: v.optional(v.string()),
  deleted: v.optional(v.boolean(), false),
});

const webhook: Handler = async (c) => {
  const secret = process.env.GITHUB_WEBHOOK_SECRET;
  if (!secret || secret.length < 32) return c.json({ detail: 'GitHub webhook unavailable' }, 503);

  const signature = c.req.header('X-Hub-Signature-256') ?? '';
  if (!/^sha256=[a-f0-9]{64}$/.test(signature)) return c.json({ detail: 'Invalid GitHub signature' }, 401);

  const body = await c.req.bytes();
  const digest = createHmac('sha256', secret).update(body).digest('hex');
  if (!timingSafeEqual(Buffer.from(`sha256=${digest}`), Buffer.from(signature))) {
    return c.json({ detail: 'Invalid GitHub signature' }, 401);
  }

  const event = c.req.header('X-GitHub-Event');
  if (event !== 'ping' && event !== 'push') return c.body(null, 204);
  const input: unknown = await c.req.json().catch(() => undefined);
  const parsed = v.safeParse(delivery, input);
  if (!parsed.success) return c.json({ detail: 'Invalid GitHub payload' }, 422);
  const { repository, ref, deleted } = parsed.output;
  if (repository.full_name.toLowerCase() !== 'skyywhyy/barsdocs'
    || (event === 'push' && (ref !== 'refs/heads/main' || deleted))) return c.body(null, 204);

  try {
    const response = await apiRequest('/internal/rag/github/sync', { method: 'POST', redirect: 'error' });
    await response.body?.cancel();
    if (response.status === 202) return c.body(null, 202);
    console.warn('GitHub RAG event rejected', response.status);
  } catch (error) {
    console.warn('GitHub RAG event failed', error instanceof Error ? error.name : 'Error');
  }
  return c.json({ detail: 'GitHub document processing unavailable' }, 503);
};

export const githubChannel = new Hono()
  .use('/webhook', bodyLimit({
    maxSize: 25 * 1024 * 1024,
    onError: (c) => c.json({ detail: 'GitHub payload too large' }, 413),
  }))
  .route('/', createChannelRouter([{ method: 'POST', path: '/webhook', handler: webhook }]));
