import { randomUUID } from 'node:crypto';
import { useModel, useResponseStart } from '@flue/runtime';

import { contextWindow, modelId } from '../provider.js';

export function Bars() {
  useModel(`bars-chat/${modelId}`, {
    compaction: {
      reserveTokens: Math.ceil(contextWindow * 0.2),
      keepRecentTokens: Math.min(Math.floor(contextWindow / 4), 8000),
    },
  });
  useResponseStart(() => ({ telegramResponseId: randomUUID() }));

  return `Ты помощник БАРС Груп. Отвечай кратко и на языке пользователя.
Помогай с общими вопросами и учитывай контекст диалога. Если для ответа
нужны внутренние сведения БАРС, скажи, что у тебя пока нет доступа к ним.
Не выдумывай внутренние правила, контакты и ссылки.
Используй Markdown для списков, ссылок и блоков кода, когда это помогает прочитать ответ.`;
}

Bars.durability = { timeoutMs: 90_000 };
