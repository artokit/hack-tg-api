import type { PromptUsage } from '@flue/runtime';

import { pool } from './db.js';

const pending = new Map<string, Set<Promise<void>>>();
const incomplete = new Set<string>();
const nanosPerUnit = 1_000_000_000n;
const usdRubRate = 821_516n;
const usdRubRateScale = 10_000n;
const lunaShort = { input: 100, cacheRead: 10, cacheWrite: 125, output: 500 };
const lunaLong = { input: 200, cacheRead: 20, cacheWrite: 250, output: 750 };

function priceInNanoUsd(model: string, usage: PromptUsage | undefined): number | null {
  if (!usage?.totalTokens || !/^(?:bars-chat\/)?(?:openai\/)?gpt-6-luna(?::documents)?$/.test(model)) return null;
  const input = usage.input + usage.cacheRead + usage.cacheWrite;
  const rate = input > 272_000 ? lunaLong : lunaShort;
  return usage.input * rate.input + usage.cacheRead * rate.cacheRead
    + usage.cacheWrite * rate.cacheWrite + usage.output * rate.output;
}

export function recordRequestModelUsage(
  instanceId: string, turnId: string, occurredAt: string, model: string, usage: PromptUsage | undefined,
): void {
  let writes = pending.get(instanceId);
  if (!writes) {
    writes = new Set();
    pending.set(instanceId, writes);
  }
  const requestWrites = writes;
  const sql = `
    INSERT INTO bars_telegram_request_model_costs (request_id, turn_id, occurred_at, cost_nano_usd)
    SELECT id, $2, $3, $4 FROM bars_telegram_requests
    WHERE instance_id = $1 AND tracks_model_cost AND $3 >= opened_at
      AND (closed_at IS NULL OR $3 <= closed_at)
    ON CONFLICT (request_id, turn_id) DO NOTHING
  `;
  const values = [instanceId, turnId, occurredAt, priceInNanoUsd(model, usage)];
  const write = pool.query(sql, values).catch(() => pool.query(sql, values)).then(() => {}, (error: unknown) => {
    incomplete.add(instanceId);
    console.warn('Support request model cost write failed', error instanceof Error ? error.name : 'Error');
  }).finally(() => {
    requestWrites.delete(write);
    if (!requestWrites.size) pending.delete(instanceId);
  });
  requestWrites.add(write);
}

export async function closedRequestCost(requestId: string, instanceId: string): Promise<string | null> {
  await Promise.all(pending.get(instanceId) ?? []);
  if (incomplete.has(instanceId)) {
    await pool.query('UPDATE bars_telegram_requests SET tracks_model_cost = false WHERE id = $1', [requestId]);
    incomplete.delete(instanceId);
    return null;
  }
  const result = await pool.query<{ cost: string | null }>(`
    SELECT CASE WHEN count(*) = count(turn.cost_nano_usd) THEN sum(turn.cost_nano_usd) END AS cost
    FROM bars_telegram_request_model_costs AS turn
    JOIN bars_telegram_requests AS request ON request.id = turn.request_id
    WHERE request.id = $1 AND request.tracks_model_cost AND turn.occurred_at <= request.closed_at
  `, [requestId]);
  const cost = result.rows[0]?.cost;
  if (cost == null) return null;
  const nanoRub = (BigInt(cost) * usdRubRate + usdRubRateScale / 2n) / usdRubRateScale;
  return `${nanoRub / nanosPerUnit}.${(nanoRub % nanosPerUnit).toString().padStart(9, '0')}`;
}
