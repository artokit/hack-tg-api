import { timingSafeEqual } from 'node:crypto';
import { createChannelRouter } from '@flue/runtime';
import { Hono, type Handler } from 'hono';
import { bodyLimit } from 'hono/body-limit';
import * as v from 'valibot';

import { httpUrl, required } from '../config.js';

const id = v.pipe(v.string(), v.regex(/^[1-9][0-9]{0,18}$/));
const pageId = v.union([id, v.pipe(v.number(), v.safeInteger(), v.minValue(1), v.transform(String))]);
const event = v.object({ space_id: v.optional(v.unknown()), page_id: pageId });

const webhook: Handler = async (c) => {
  const secret = process.env.CONFLUENCE_WEBHOOK_SECRET?.trim();
  if (!secret) return c.json({ detail: 'Confluence webhook unavailable' }, 503);

  const expected = Buffer.from(secret);
  const provided = Buffer.from(c.req.header('X-Webhook-Secret') ?? '');
  if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
    return c.json({ detail: 'Invalid webhook secret' }, 401);
  }

  const input: unknown = await c.req.json().catch(() => undefined);
  const parsed = v.safeParse(event, input);
  if (!parsed.success) return c.json({ detail: 'Invalid Confluence event' }, 400);
  const configuredSpace = process.env.CONFLUENCE_SPACE_ID?.trim();
  if (configuredSpace && !v.is(id, configuredSpace)) {
    return c.json({ detail: 'Invalid Confluence space configuration' }, 503);
  }
  const spaceId = configuredSpace || parsed.output.space_id;
  if (!v.is(id, spaceId)) return c.json({ detail: 'Invalid Confluence event' }, 400);

  try {
    const response = await fetch(`${httpUrl('API_URL')}/internal/rag/confluence/imports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Bot-Token': required('BOT_API_TOKEN') },
      body: JSON.stringify({ space_id: spaceId, page_id: parsed.output.page_id }),
      signal: AbortSignal.timeout(5000),
      redirect: 'error',
    });
    await response.body?.cancel();
    if (response.status === 202) return c.body(null, 202);
    console.warn('Confluence import queue rejected request', response.status);
  } catch (error) {
    console.warn('Confluence import queue unavailable', error instanceof Error ? error.name : 'Error');
  }
  return c.json({ detail: 'Confluence import queue unavailable' }, 503);
};

export const confluenceChannel = new Hono()
  .use('/webhook', bodyLimit({
    maxSize: 4096,
    onError: (c) => c.json({ detail: 'Invalid Confluence event' }, 400),
  }))
  .route('/', createChannelRouter([{ method: 'POST', path: '/webhook', handler: webhook }]));
