import { randomUUID } from 'node:crypto';
import { useDataWriter, useDelivery, useModel, useResponseStart, useTool } from '@flue/runtime';

import { contextWindow, modelId } from '../provider.js';
import { answerTool, ragEnabled } from '../rag.js';

export function Bars() {
  useModel(`bars-chat/${modelId}`, {
    compaction: {
      reserveTokens: Math.ceil(contextWindow * 0.2),
      keepRecentTokens: Math.min(Math.floor(contextWindow / 4), 8000),
    },
  });
  useResponseStart(() => ({ telegramResponseId: randomUUID() }));
  const writeRag = useDataWriter('ragAnswer');
  const delivery = useDelivery();
  if (ragEnabled && delivery.kind === 'user') {
    useTool(answerTool(delivery.body, writeRag));
  }

  const documentation = ragEnabled
    ? `Для вопросов о внутренних правилах и документации БАРС, интерфейсе БАРС-Офиса,
бизнес-процессах, реестрах и конкретных пунктах вызывай answer_from_docs. Повторно вызывай
тулзу для уточнений к таким вопросам, используя контекст диалога в standalone_question.
На приветствия и общие вопросы отвечай напрямую. Не отвечай по внутренним сведениям по памяти.`
    : 'Если нужны внутренние сведения БАРС, скажи, что у тебя пока нет доступа к ним.';
  return `Ты помощник БАРС Груп. Отвечай кратко и на языке пользователя.
Помогай с общими вопросами и учитывай контекст диалога. ${documentation}
Не выдумывай внутренние правила, контакты и ссылки.
Используй Markdown для списков, ссылок и блоков кода, когда это помогает прочитать ответ.`;
}

Bars.durability = { timeoutMs: 90_000 };
