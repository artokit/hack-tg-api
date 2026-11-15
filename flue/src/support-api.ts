import { botRequest } from './bot-api.js';
import type { ClosedRequest, HandoffDraft } from './support-request.js';

async function createIfMissing(readPath: string, createPath: string, body: object): Promise<void> {
  const existing = await botRequest(readPath);
  if (existing.ok) return;
  if (existing.status !== 404) throw new Error(`Support API status ${existing.status}`);
  const created = await botRequest(createPath, { method: 'POST', body: JSON.stringify(body) });
  if (created.ok || (created.status === 409 && (await botRequest(readPath)).ok)) return;
  throw new Error(`Support API status ${created.status}`);
}

export function saveClosedRequest(event: ClosedRequest): Promise<void> {
  const { request_id, handoff: _handoff, ...outcome } = event;
  return createIfMissing(`support-requests/${request_id}`, 'support-requests', { id: request_id, ...outcome });
}

export function queueSupportTicket(id: string, draft: HandoffDraft, conversation: string): Promise<void> {
  const path = `support-requests/${id}/ticket`;
  return createIfMissing(path, path, { ...draft, conversation });
}
