import { randomUUID } from 'node:crypto';
import {
  useAgentFinish, useAgentStart, useDataWriter, useDelivery, useModel, usePersistentState,
  useResponseStart, useTool,
} from '@flue/runtime';

import { contextWindow, modelId } from '../provider.js';
import { answerTool } from '../rag.js';
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
    const [status, setStatus] = usePersistentState<'pending' | 'reminded' | 'handled'>(
      'telegramReplyStatus', 'pending',
    );
    useAgentStart(() => setStatus('pending'));
    useTool(answerTool(Bars, delivery.body, (result) => {
      writeRag(result);
      setStatus('handled');
    }));
    useTool(chatTool((kind) => {
      writeChat(kind);
      setStatus('handled');
    }));
    useAgentFinish(({ append }) => {
      if (status !== 'pending') return;
      setStatus('reminded');
      append({ kind: 'signal', type: 'reply_tool_required', body: 'Вызови один подходящий инструмент ответа.' });
    });
  }

  return `Ты помощник БАРС Груп. Выбери инструмент для ответа пользователю.
Если пользователь просит написать, исправить или сгенерировать код либо решить задачу по
программированию, вызови reply_in_chat с kind=coding_task. Пример такой просьбы: «напиши бабл сорт».
Для поиска инструкции, готового примера из документации или ответа на вопрос вызывай answer_from_docs.
Ищи и по общим темам, например когда просят помочь настроить принтер.
Для уточнения или составного вопроса учитывай историю диалога и передавай самостоятельные вопросы
в questions, сохраняя точные названия и ID. Включай в вопросы только сведения, нужные для поиска ответа.
Для приветствия, благодарности, прощания или вопроса о твоих возможностях используй reply_in_chat.
Если сообщение начинается с приветствия, выбери инструмент по основной просьбе пользователя.`;
}

Bars.durability = { timeoutMs: 90_000 };
