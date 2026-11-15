import { randomUUID } from 'node:crypto';
import { useDataWriter, useDelivery, useModel, useResponseStart, useTool } from '@flue/runtime';

import { contextWindow, modelId } from '../provider.js';
import { answerTool } from '../rag.js';
import { transientSignal } from '../transient-harness.js';

export function Bars() {
  const delivery = useDelivery();
  if (delivery.kind === 'signal' && delivery.type === transientSignal) {
    useModel(`bars-chat/${modelId}`, { compaction: false });
    return 'Ты формулируешь ответы по переданным фрагментам документации БАРС.';
  }
  useModel(`bars-chat/${modelId}`, {
    compaction: {
      reserveTokens: Math.ceil(contextWindow * 0.2),
      keepRecentTokens: Math.min(Math.floor(contextWindow / 4), 8000),
    },
  });
  useResponseStart(() => ({ telegramResponseId: randomUUID() }));
  const writeRag = useDataWriter('ragAnswer');
  if (delivery.kind === 'user') {
    useTool(answerTool(Bars, delivery.body, writeRag));
  }

  return `Ты помощник БАРС Груп. Отвечай кратко и на языке пользователя.
Помогай с общими вопросами и учитывай контекст диалога.
Для вопросов о внутренних правилах и документации БАРС, интерфейсе БАРС-Офиса,
бизнес-процессах, реестрах и конкретных пунктах вызывай answer_from_docs. Повторно вызывай
тулзу для уточнений к таким вопросам, передавая самостоятельные вопросы в questions.
Не утверждай, что пункт или документ не найден, без вызова answer_from_docs для текущего вопроса.
На приветствия и общие вопросы отвечай напрямую. Не отвечай по внутренним сведениям по памяти.
Не выдумывай внутренние правила, контакты и ссылки.
Используй Markdown для списков, ссылок и блоков кода, когда это помогает прочитать ответ.`;
}

Bars.durability = { timeoutMs: 90_000 };
