import { timingSafeEqual } from 'node:crypto';
import { Hono } from 'hono';
import { bodyLimit } from 'hono/body-limit';
import * as v from 'valibot';

import { DocumentImport, importOperations } from './agents/documents.js';
import { withTransientHarness } from './transient-harness.js';

const request = v.object({
  operation: v.picklist(importOperations),
  data: v.record(v.string(), v.unknown()),
  image: v.optional(v.pipe(v.string(), v.maxLength(14 * 1024 * 1024), v.base64())),
});
const string = v.string();
const integer = v.pipe(
  v.union([v.number(), v.pipe(v.string(), v.regex(/^\d+$/), v.transform(Number))]),
  v.safeInteger(),
);
const outputs = {
  read_visual: v.object({
    text: v.pipe(string, v.maxLength(18000)),
    columns: v.optional(v.pipe(v.array(string), v.maxLength(40)), []),
    rows: v.optional(v.pipe(v.array(v.object({
      cells: v.pipe(v.array(string), v.maxLength(40)),
    })), v.maxLength(150)), []),
  }),
  plan_chunks: v.object({
    groups: v.pipe(v.array(v.object({
      first: integer, last: integer,
      related: v.optional(v.pipe(v.array(integer), v.maxLength(8)), []),
    })), v.minLength(1), v.maxLength(36)),
  }),
};

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
  const { operation, data, image } = parsed.output;
  if ((operation === 'read_visual') !== Boolean(image)) {
    return c.json({ detail: 'Image required only for visual reading' }, 400);
  }
  let text: string;
  const signal = AbortSignal.any([c.req.raw.signal, AbortSignal.timeout(20_000)]);
  try {
    const reply = await withTransientHarness(DocumentImport, { operation }, async (harness) => harness.prompt(
      JSON.stringify(data),
      { signal, ...(image ? { images: [{ type: 'image', data: image, mimeType: 'image/png' }] } : {}) },
    ));
    text = reply.text.trim();
  } catch {
    console.warn('Flue RAG model call failed', operation);
    return c.json({ detail: 'Model unavailable' }, 503);
  }
  try {
    const output: unknown = JSON.parse(text.replace(/^\`\`\`(?:json)?\s*([\s\S]+?)\s*\`\`\`$/i, '$1'));
    return c.json(v.parse(outputs[operation], output));
  } catch {
    return c.json({ detail: 'Invalid model output' }, 422);
  }
});
