import * as v from 'valibot';

export const supportRequestCategory = v.picklist([
  'access', 'navigation', 'search_filters', 'documents_records',
  'business_processes', 'employees_contacts', 'other',
]);
export type SupportRequestCategory = v.InferOutput<typeof supportRequestCategory>;

export interface ReplyFlags {
  hasAnswer: boolean;
  hasClarification: boolean;
}

export const handoffDraft = v.object({
  title: v.pipe(v.string(), v.trim(), v.minLength(5), v.maxLength(255)),
  description: v.pipe(v.string(), v.trim(), v.minLength(1)),
});
export type HandoffDraft = v.InferOutput<typeof handoffDraft>;

const handoffReason = v.picklist(['rag_exhausted', 'operator_requested']);

export const requestedCloseReason = v.picklist(['confirmed', 'user_requested']);
export const supportAction = v.variant('action', [
  v.object({ action: v.literal('ban') }),
  v.object({ action: v.literal('close'), reason: requestedCloseReason }),
]);
export type SupportAction = v.InferOutput<typeof supportAction>;

const closeReason = v.picklist([
  'thanks', 'user_closed', 'feedback_timeout', 'clarification_timeout', 'details_timeout',
  'technical_timeout', 'delivery_failed', 'spam', ...requestedCloseReason.options, ...handoffReason.options,
]);
export type CloseReason = v.InferOutput<typeof closeReason>;

export function resolution(reason: CloseReason): boolean | null {
  if (reason === 'confirmed' || reason === 'thanks') return true;
  if (reason === 'details_timeout' || reason === 'rag_exhausted' || reason === 'operator_requested') return false;
  return null;
}

const operatorTarget = '(?:оператор(?:а|у|ом)?|специалист(?:а|у|ом)?|(?:живого )?человек(?:а|у|ом)?|поддержк[ауе]|поддержкой)';
const operatorRequests = [
  operatorTarget,
  `(?:передай(?:те)?|передать|переключи(?:те)?|переключить|позови(?:те)?|позвать|свяжи(?:те)?|связаться|поговорить)\\s+(?:(?:этот вопрос|это обращение|вопрос|обращение|проблему|меня|нас|мне)\\s+)?(?:(?:на|с|в)\\s+)?${operatorTarget}`,
  '(?:создай(?:те)?|создать|заведи(?:те)?|завести)\\s+(?:тикет|заявку)',
].join('|');
const operatorRequest = new RegExp(
  `^(?:(?:спасибо|пожалуйста)[,.!\\s]+)?(?:(?:мне|нам)\\s+)?(?:(?:можешь|можете|можно(?: ли)?|хочу|прошу|давай(?:те)?|нужен|нужна)\\s+)?(?:${operatorRequests})(?:[\\s,]+пожалуйста)?$`,
  'u',
);

export function isOperatorRequest(text: string): boolean {
  return operatorRequest.test(text);
}

export const supportRequestClosed = 'support_request_closed';
export const closedRequest = v.object({
  request_id: v.pipe(v.string(), v.uuid()),
  instance_id: v.string(),
  telegram_chat_id: v.string(),
  category_id: v.nullable(v.string()),
  opened_at: v.string(),
  closed_at: v.string(),
  is_resolved: v.nullable(v.boolean()),
  close_reason: closeReason,
  handoff: v.optional(handoffDraft),
});
export type ClosedRequest = v.InferOutput<typeof closedRequest>;
