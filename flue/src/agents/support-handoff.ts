import { defineTool } from '@flue/runtime';

import { handoffDraft, type SupportHandoff } from '../support-request.js';

export function handoffTool(
  repeatedMiss: boolean, write: (handoff: SupportHandoff) => void,
) {
  return defineTool({
    name: 'handoff_to_support',
    description: 'Передай вопрос оператору, если сотрудник прямо попросил об этом или повторный поиск после уточнения вернул handoff_required. Укажи суть вопроса и что осталось нерешённым.',
    input: handoffDraft,
    run({ data }) {
      write({ ...data, reason: repeatedMiss ? 'rag_exhausted' : 'operator_requested' });
      return { output: 'Передача вопроса оператору поставлена в очередь.', terminate: true };
    },
  });
}
