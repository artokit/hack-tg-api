import { timingSafeEqual } from 'node:crypto';
import { init } from '@flue/runtime';
import { Hono } from 'hono';
import { bodyLimit } from 'hono/body-limit';
import * as v from 'valibot';

import { answerOperations, DocumentAnswer, DocumentImport, importOperations } from './agents/documents.js';

const operations = [...importOperations, ...answerOperations] as const;
const request = v.object({
  operation: v.picklist(operations),
  data: v.record(v.string(), v.unknown()),
  schema: v.record(v.string(), v.unknown()),
  image: v.optional(v.pipe(v.string(), v.maxLength(14 * 1024 * 1024), v.base64())),
});

export const ragModel = new Hono();

ragModel.post('/model', async (c, next) => {
  const expected = process.env.BOT_API_TOKEN?.trim();
  const provided = c.req.header('X-Bot-Token');
  if (!expected || !provided) return c.json({ detail: 'Invalid bot token' }, 401);
  const secret = Buffer.from(expected);
  const token = Buffer.from(provided);
  if (secret.length !== token.length || !timingSafeEqual(secret, token)) {
    return c.json({ detail: 'Invalid bot token' }, 401);
  }
  await next();
}, bodyLimit({ maxSize: 15 * 1024 * 1024 }), async (c) => {
  let input: unknown;
  try {
    input = await c.req.json();
  } catch {
    return c.json({ detail: 'Invalid JSON' }, 400);
  }
  const parsed = v.safeParse(request, input);
  if (!parsed.success) return c.json({ detail: 'Invalid model request' }, 400);
  const { operation, data, schema, image } = parsed.output;
  if ((operation === 'read_visual') !== Boolean(image)) {
    return c.json({ detail: 'Image required only for visual reading' }, 400);
  }
  let text: string;
  const agent = init(operation === 'read_visual' || operation === 'plan_chunks' ? DocumentImport : DocumentAnswer);
  const signal = AbortSignal.any([c.req.raw.signal, AbortSignal.timeout(20_000)]);
  try {
    const receipt = await agent.dispatch({
      initialData: { operation, schema },
      message: {
        kind: 'user',
        body: JSON.stringify(data),
        ...(image ? { attachments: [{ type: 'image', data: image, mimeType: 'image/png' }] } : {}),
      },
    });
    text = (await agent.read(receipt, { signal })).text.trim();
  } catch {
    if (signal.aborted) void agent.abort().catch(() => {});
    console.warn('Flue RAG model call failed', operation);
    return c.json({ detail: 'Model unavailable' }, 503);
  }
  try {
    const output: unknown = JSON.parse(text.replace(/^\`\`\`(?:json)?\s*([\s\S]+?)\s*\`\`\`$/i, '$1'));
    return c.json(output);
  } catch {
    return c.json({ detail: 'Invalid model output' }, 422);
  }
});
