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
    description: 'Заверши текущее обращение, только если пользователь явно подтвердил решение проблемы (confirmed) или попросил закрыть обращение либо закончить разговор (user_requested). Не закрывай нерешённый вопрос без просьбы пользователя. Сохранение истории и новый контекст обеспечит бот.',
    input: v.object({ reason: requestedCloseReason }),
    run({ data }) {
      write({ action: 'close', reason: data.reason });
      return { output: 'Закрытие обращения и передача на сохранение запрошены.', terminate: true };
    },
  });
}
