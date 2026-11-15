import { setTimeout as delay } from 'node:timers/promises';

import * as v from 'valibot';

import { apiRequest, botRequest } from './bot-api.js';
import type { ClosedRequest, HandoffDraft, SupportRequestCategory } from './support-request.js';

export async function saveClosedRequest(
  event: ClosedRequest, cost: string | null, classify: () => Promise<SupportRequestCategory>,
): Promise<void> {
  const { request_id, handoff: _handoff, ...outcome } = event;
  const readPath = `support-requests/${request_id}`;
  const existing = await botRequest(readPath);
  if (existing.ok) return;
  if (existing.status !== 404) throw new Error(`Support API status ${existing.status}`);
  const category = await classify();
  const created = await botRequest('support-requests', {
    method: 'POST',
    body: JSON.stringify({ id: request_id, ...outcome, category_id: category, model_cost_rub: cost }),
  });
  if (created.ok || (created.status === 409 && (await botRequest(readPath)).ok)) return;
  throw new Error(`Support API status ${created.status}`);
}

const ticketRead = v.object({
  status: v.string(),
  external_key: v.nullable(v.string()),
  external_url: v.nullish(v.pipe(v.string(), v.url())),
});

export async function getSupportTicketUrl(id: string): Promise<string> {
  const response = await botRequest(`support-requests/${id}/ticket`);
  if (!response.ok) throw new Error(`Ticket API status ${response.status}`);
  const ticket = v.parse(ticketRead, await response.json());
  if (ticket.status !== 'created' || !ticket.external_url) {
    throw new Error('Jira ticket link is not available yet');
  }
  return ticket.external_url;
}

async function waitForSupportTicket(id: string, draft: HandoffDraft): Promise<void> {
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
    if (ticket.status === 'created' && ticket.external_key) return;
    if (ticket.status === 'failed' || Date.now() >= deadline) break;
    await delay(1_000);
    response = await botRequest(path);
  }
  if (!response.ok) throw new Error(`Ticket API status ${response.status}`);
  throw new Error('Jira ticket creation has not been confirmed yet');
}

export async function createSupportTicket(id: string, draft: HandoffDraft, conversation: string): Promise<void> {
  await waitForSupportTicket(id, {
    ...draft,
    description: `${draft.description}\n\nПереписка по обращению:\n\n${conversation}`,
  });
}
