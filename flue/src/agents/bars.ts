import { randomUUID } from 'node:crypto';
import {
  useAgentFinish, useAgentStart, useDataWriter, useDelivery, useModel, usePersistentState,
  useResponseStart, useTool,
} from '@flue/runtime';

import { contextWindow, modelId } from '../provider.js';
import { answerTool, needsRagClarification } from '../rag.js';
import { chatTool } from '../telegram-chat.js';
import { transientSignal } from '../transient-harness.js';
import { handoffTool } from './support-handoff.js';

const handoffRequiredSignal = 'support_handoff_required';

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
  const writeHandoff = useDataWriter('supportHandoff');
  const handoffReminder = delivery.kind === 'signal' && delivery.type === handoffRequiredSignal;
  if (delivery.kind === 'user' || handoffReminder) {
    const [status, setStatus] = usePersistentState<
      'pending' | 'reminded' | 'handled' | 'handoff_required' | 'handoff_reminded'
    >(
      'telegramReplyStatus', 'pending',
    );
    const [unclear, setUnclear] = usePersistentState<{ question: string; clarification?: string } | null>(
      'supportClarification', null,
    );
    if (delivery.kind === 'user') useAgentStart(() => setStatus('pending'));
    const repeatedMiss = handoffReminder || status === 'handoff_required' || status === 'handoff_reminded';
    useTool(handoffTool(repeatedMiss, (handoff) => {
      writeHandoff(handoff);
      setStatus('handled');
    }));
    if (!repeatedMiss && delivery.kind === 'user') {
      useTool(answerTool(Bars, delivery.body, (result) => {
        writeRag(result);
        const needsClarification = needsRagClarification(result);
        const retryFailed = unclear !== null && needsClarification;
        if (needsClarification) {
          setUnclear(unclear ? { ...unclear, clarification: delivery.body } : { question: delivery.body });
        } else if (result.status === 'answered') {
          setUnclear(null);
        }
        setStatus(retryFailed ? 'handoff_required' : 'handled');
        return retryFailed;
      }));
      useTool(chatTool((kind) => {
        writeChat(kind);
        setStatus('handled');
      }));
    }
    useAgentFinish(({ append }) => {
      if (status === 'handoff_required') {
        setStatus('handoff_reminded');
        append({ kind: 'signal', type: handoffRequiredSignal, body: 'Повторный поиск не помог. Вызови handoff_to_support с заголовком и описанием проблемы из переписки.' });
        return;
      }
      if (status === 'handoff_reminded' && unclear) {
        writeHandoff({
          reason: 'rag_exhausted',
          title: 'Требуется помощь по обращению',
          description: [unclear.question, unclear.clarification].filter(Boolean).join('\n\n'),
        });
        setStatus('handled');
        return;
      }
      if (status !== 'pending') return;
      setStatus('reminded');
      append({ kind: 'signal', type: 'reply_tool_required', body: 'Вызови один подходящий инструмент ответа.' });
    });
  }

  return `Ты помощник БАРС Груп. Выбери инструмент для ответа пользователю.
Если сотрудник прямо просит передать вопрос человеку или оператору, вызови handoff_to_support.
Если answer_from_docs вернул handoff_required=true, сразу вызови handoff_to_support. Включи
исходный вопрос, полезные детали из уточнения и то, что осталось нерешённым.
В остальных случаях продолжай разбирать вопрос. Ответ «Нет» сам по себе не является просьбой о передаче.
Если пользователь просит написать, исправить или сгенерировать код либо решить задачу по
программированию, вызови reply_in_chat с kind=coding_task. Пример такой просьбы: «напиши бабл сорт».
Для поиска инструкции, готового примера из документации или ответа на вопрос вызывай answer_from_docs.
Ищи и по общим темам, например когда просят помочь настроить принтер.
Для поиска передавай lookup. Поле query используется как ключ кэша, поэтому вопросы с одной целью
и одинаковыми условиями должны давать посимвольно одинаковый query. Составляй его как короткий
заголовок инструкции в порядке «действие или искомый факт, объект, условия». Пиши обычные слова в
нижнем регистре, без знака вопроса. Сохраняй точные названия, ID, версии и остальные явные условия.
Опускай вежливые обороты и указания вроде «найди актуальную инструкцию».
Если спрашивают, где найти объект, начинай query словами «где найти». Названия реестров приводи
к форме «реестр чего», например «мебельный реестр» и «реестр по мебели» дают «реестр мебели».
Для общей первичной настройки принтера в Windows используй query «настройка принтера в Windows».
Эта форма включает просьбы «как подключить принтер на винде» и «как добавить принтер в Windows».
Конкретный шаг или версия остаются в query. Например, «установка драйвера принтера в Windows 11».
Для самостоятельного вопроса используй kind=standalone.
Для уточнения, которое зависит от предыдущих сообщений, используй kind=follow_up и восстанови
нужный контекст в query. Для нескольких независимых вопросов используй kind=split.
Для приветствия, благодарности, прощания или вопроса о твоих возможностях используй reply_in_chat.
Если сообщение начинается с приветствия, выбери инструмент по основной просьбе пользователя.`;
}

Bars.durability = { timeoutMs: 90_000 };
