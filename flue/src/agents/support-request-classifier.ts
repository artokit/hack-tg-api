import { useModel, useSkill } from '@flue/runtime';
import * as v from 'valibot';

import { contextWindow, modelId } from '../provider.js';
import { supportRequestCategorySkill } from '../skills/support-request-category.js';
import { supportRequestCategory, type SupportRequestCategory } from '../support-request.js';
import { withTransientHarness } from '../transient-harness.js';

function SupportRequestClassifier() {
  useModel(`bars-chat/${modelId}`, { compaction: false });
  useSkill(supportRequestCategorySkill);
  return 'Сначала активируй скилл support-request-category. По его правилам определи категорию переданной переписки.';
}

export async function classifySupportRequest(conversation: string): Promise<SupportRequestCategory> {
  const maxLength = Math.min(20_000, contextWindow);
  const edge = Math.floor(maxLength / 2);
  const preview = conversation.length > maxLength
    ? conversation.slice(0, edge) + '\n[…]\n' + conversation.slice(-edge)
    : conversation;
  const reply = await withTransientHarness(SupportRequestClassifier, undefined, (harness) => harness.prompt(
    preview, { signal: AbortSignal.timeout(20_000) },
  ));
  return v.parse(supportRequestCategory, reply.text.trim());
}
