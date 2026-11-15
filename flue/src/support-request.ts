import * as v from 'valibot';

export const handoffDraft = v.object({
  title: v.pipe(v.string(), v.trim(), v.minLength(5), v.maxLength(255)),
  description: v.pipe(v.string(), v.trim(), v.minLength(1)),
});
export type HandoffDraft = v.InferOutput<typeof handoffDraft>;

const handoffReason = v.picklist(['rag_exhausted', 'operator_requested']);
export const supportHandoff = v.object({ ...handoffDraft.entries, reason: handoffReason });
export type SupportHandoff = v.InferOutput<typeof supportHandoff>;

const closeReason = v.picklist([
  'confirmed', 'thanks', 'feedback_timeout', 'clarification_timeout', 'details_timeout',
  'technical_timeout', 'reset', 'delivery_failed', ...handoffReason.options,
]);
export type CloseReason = v.InferOutput<typeof closeReason>;

export function resolution(reason: CloseReason): boolean | null {
  if (reason === 'confirmed' || reason === 'thanks') return true;
  if (reason === 'details_timeout' || reason === 'rag_exhausted' || reason === 'operator_requested') return false;
  return null;
}

const operatorTarget = '(?:оператор[ау]?|специалист[ау]?|человек(?:а|у|ом)?|поддержк[ауе]|тикет[ау]?)(?![\\p{L}])';
const imperativeRequest = new RegExp(
  `(?<![\\p{L}])(?:передай|позови|свяжи|переключи|создай|заведи)(?:те)?[\\s,]+[^.!?]{0,100}${operatorTarget}`,
  'iu',
);
const politeRequest = new RegExp(
  `(?<![\\p{L}])(?:можешь|можете|можно(?: ли)?|хочу|прошу|давай(?:те)?)\\s+(?:(?:пожалуйста|мне|нам)\\s+){0,2}(?:(?:передать|позвать|связаться|поговорить|переключить|создать|завести)\\s+[^.!?]{0,100})?${operatorTarget}`,
  'iu',
);
const shortOperatorRequest = new RegExp(`^${operatorTarget}[,\\s]+пожалуйста[.!\\s]*$`, 'iu');
const deniedOperatorRequest = /(?<![\p{L}])не\s+(?:надо|нужно|хочу|передавай(?:те)?|передай(?:те)?|зови(?:те)?|создавай(?:те)?|создай(?:те)?|заводи(?:те)?|переключай(?:те)?)(?![\p{L}])/iu;

export function isOperatorRequest(text: string): boolean {
  const message = text.normalize('NFKC');
  return !deniedOperatorRequest.test(message)
    && (imperativeRequest.test(message) || politeRequest.test(message) || shortOperatorRequest.test(message));
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
