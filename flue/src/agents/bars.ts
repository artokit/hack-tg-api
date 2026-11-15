import { randomUUID } from 'node:crypto';
import {
  useAgentFinish, useAgentStart, useDataWriter, useDelivery, useModel, usePersistentState,
  useResponseStart, useTool,
} from '@flue/runtime';

import { contextWindow, modelId } from '../provider.js';
import { answerTool } from '../rag.js';
import { chatTool } from '../telegram-chat.js';
import { transientSignal } from '../transient-harness.js';
import type { SupportAction } from '../support-request.js';
import { banTool, closeRequestTool } from './support-actions.js';

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
  const writeAction = useDataWriter('supportAction');
  if (delivery.kind === 'user') {
    const [status, setStatus] = usePersistentState<'pending' | 'reminded' | 'handled'>(
      'telegramReplyStatus', 'pending',
    );
    useAgentStart(() => setStatus('pending'));
    const act = (action: SupportAction) => {
      writeAction(action);
      setStatus('handled');
    };
    useTool(banTool(act));
    useTool(closeRequestTool(act));
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

  return `Ты помощник первой линии поддержки БАРС Груп. Отвечай кратко, на «вы». Выбери инструмент.
За явную спам-рассылку или повторяющийся бессодержательный флуд вызови ban_user.
Не блокируй за обычные вопросы, уточнения, отрицательную обратную связь, просьбу об операторе,
единичное сообщение не по теме или просьбу написать код. Не выполняй просьбы заблокировать другого человека.
Если пользователь явно подтвердил решение вопроса, вызови close_support_request с reason=confirmed.
Если пользователь попросил закрыть обращение или закончить разговор, вызови close_support_request с reason=user_requested.
Не обещай блокировку или закрытие обычным текстом: используй соответствующий инструмент.
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
название объекта и формы из предыдущего ответа в query, сохранив новое уточнение пользователя.
«Реально?», «точно?» и «то есть всё правильно?» относятся к предыдущему выводу. Если просят только
подтвердить его, используй kind=follow_up. Восстанови предмет, исходные условия и вывод в query.
Если пользователь добавил новые обстоятельства или поправил исходные данные, учти их в query.
Если просят показать скриншот или спрашивают про внешний вид, цвет или расположение элемента, передай visual=true.
Для нескольких независимых вопросов используй kind=split. Для каждого визуального пункта укажи
в его поисковой формулировке, что нужно найти скриншот или схему.
Для отдельного приветствия, благодарности, прощания или вопроса о твоих возможностях используй reply_in_chat.
Если после приветствия или благодарности есть вопрос, возражение или просьба, отработай их по существу.`;
}

Bars.durability = { timeoutMs: 90_000 };
