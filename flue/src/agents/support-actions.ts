import { defineTool } from '@flue/runtime';
import * as v from 'valibot';

import { requestedCloseReason, type SupportAction } from '../support-request.js';

export function reportSpamTool(report: () => void) {
  return defineTool({
    name: 'report_spam',
    description: 'Отметь текущую реплику, только если это явный спам или часть бессодержательного потока. Затем выбери инструмент ответа. Отдельная отметка не блокирует сотрудника.',
    input: v.object({}),
    run() {
      report();
      return 'Реплика отмечена. Выбери, как её обработать.';
    },
  });
}

export function closeRequestTool(write: (action: SupportAction) => void) {
  return defineTool({
    name: 'close_support_request',
    description: 'Закрой текущее обращение, если сотрудник явно сообщил, что проблема решена (confirmed), или прямо попросил закрыть обращение либо согласился на закрытие (user_requested).',
    input: v.object({ reason: requestedCloseReason }),
    run({ data }) {
      write({ action: 'close', reason: data.reason });
      return { output: 'Закрытие обращения и передача на сохранение запрошены.', terminate: true };
    },
  });
}

export function offerCloseRequestTool(write: (action: SupportAction) => void) {
  return defineTool({
    name: 'offer_close_support_request',
    description: 'Предложи закрыть открытое обращение, если по контексту сотрудник завершает разговор и больше ничего не просит. Бот сразу покажет кнопки подтверждения.',
    input: v.object({}),
    run() {
      write({ action: 'offer_close' });
      return { output: 'Бот спросит, закрыть ли обращение.', terminate: true };
    },
  });
}
