import { defineTool } from '@flue/runtime';
import * as v from 'valibot';

import { requestedCloseReason, type SupportAction } from '../support-request.js';

export function banTool(write: (action: SupportAction) => void) {
  return defineTool({
    name: 'ban_user',
    description: 'Заблокируй текущего пользователя за явную спам-рассылку или повторяющийся бессодержательный флуд. Не блокируй за обычные вопросы, уточнения, отрицательную обратную связь, просьбу об операторе или единичное сообщение не по теме. ID и срок определит бот автоматически.',
    input: v.object({}),
    run() {
      write({ action: 'ban' });
      return { output: 'Блокировка за флуд или спам запрошена. Бот сообщит срок пользователю.', terminate: true };
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
