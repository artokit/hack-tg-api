import { randomUUID } from 'node:crypto';
import {
  useAgentFinish, useAgentStart, useDataWriter, useDelivery, useModel, usePersistentState,
  useResponseStart, useTool,
} from '@flue/runtime';

import { contextWindow, modelId } from '../provider.js';
import { answerFromDocs, answerTool } from '../rag.js';
import { chatTool } from '../telegram-chat.js';
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
  const writeChat = useDataWriter('chatAnswer');
  if (delivery.kind === 'user') {
    const [handled, setHandled] = usePersistentState('telegramReplyHandled', false);
    useAgentStart(() => setHandled(false));
    useTool(answerTool(Bars, delivery.body, (result) => {
      writeRag(result);
      setHandled(true);
    }));
    useTool(chatTool((kind) => {
      writeChat(kind);
      setHandled(true);
    }));
    useAgentFinish(async ({ signal }) => {
      if (!handled) writeRag(await answerFromDocs(Bars, delivery.body, undefined, signal));
    });
  }

  return `Ты помощник БАРС Груп. Выбери инструмент для ответа пользователю.
На любой вопрос о фактах вызывай answer_from_docs, даже если тема кажется общей.
Для уточнения или составного вопроса учитывай историю диалога и передавай самостоятельные вопросы
в questions, сохраняя точные названия и ID. Каждый новый вопрос о фактах требует нового поиска.
Вызывай reply_in_chat для приветствий, благодарностей, прощаний и вопросов о твоих возможностях.
Если пользователь просит выполнить постороннюю задачу, например написать пузырьковую сортировку,
вызови reply_in_chat с kind=off_topic.`;
}

Bars.durability = { timeoutMs: 90_000 };
