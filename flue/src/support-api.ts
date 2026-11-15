import { setTimeout as delay } from 'node:timers/promises';

import * as v from 'valibot';

import { apiRequest, botRequest } from './bot-api.js';
import type { ClosedRequest, HandoffDraft } from './support-request.js';

async function createIfMissing(readPath: string, createPath: string, body: object): Promise<void> {
  const existing = await botRequest(readPath);
  if (existing.ok) return;
  if (existing.status !== 404) throw new Error(`Support API status ${existing.status}`);
  const created = await botRequest(createPath, { method: 'POST', body: JSON.stringify(body) });
  if (created.ok || (created.status === 409 && (await botRequest(readPath)).ok)) return;
  throw new Error(`Support API status ${created.status}`);
}

export function saveClosedRequest(event: ClosedRequest, cost: number | null): Promise<void> {
  const { request_id, handoff: _handoff, ...outcome } = event;
  return createIfMissing(`support-requests/${request_id}`, 'support-requests', {
    id: request_id, ...outcome, model_cost_usd: cost,
  });
}

const ticketRead = v.object({ id: v.number(), status: v.string(), external_key: v.nullable(v.string()) });

async function supportTicketId(id: string, draft: HandoffDraft): Promise<number> {
  const path = `support-requests/${id}/ticket`;
  let response = await botRequest(path);
  if (response.status === 404) {
    const created = await apiRequest('/tickets', {
      method: 'POST',
      body: JSON.stringify({ ...draft, support_request_id: id }),
    });
    if (!created.ok && created.status !== 409) throw new Error(`Ticket API status ${created.status}`);
    response = await botRequest(path);
  }
  const deadline = Date.now() + 12_000;
  while (response.ok) {
    const ticket = v.parse(ticketRead, await response.json());
    if (ticket.status === 'created' && ticket.external_key) return ticket.id;
    if (ticket.status === 'failed' || Date.now() >= deadline) break;
    await delay(1_000);
    response = await botRequest(path);
  }
  if (!response.ok) throw new Error(`Ticket API status ${response.status}`);
  throw new Error('Jira ticket is not available for attachment yet');
}

export async function attachSupportConversation(id: string, draft: HandoffDraft, conversation: string): Promise<void> {
  const ticketId = await supportTicketId(id, draft);
  const form = new FormData();
  form.set('file', new Blob([conversation], { type: 'text/plain;charset=utf-8' }), `conversation-${id}.txt`);
  form.set('public', 'false');
  const response = await botRequest(`tickets/${ticketId}/attachments`, {
    method: 'POST', body: form, signal: AbortSignal.timeout(150_000),
  });
  if (response.ok) return;
  if (response.status === 409 && (await response.json() as { detail?: string }).detail === 'Переписка уже прикреплена') return;
  throw new Error(`Ticket attachment API status ${response.status}`);
}
