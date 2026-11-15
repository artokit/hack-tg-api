import { defineTool } from '@flue/runtime';
import * as v from 'valibot';

const replies = {
  greeting: 'Здравствуйте! Я БАРС, помощник поддержки БАРС Груп. Помогу найти ответ в документации. Если нужен специалист, напишите «оператор». Чем помочь?',
  thanks: 'Пожалуйста!',
  farewell: 'До встречи!',
  capabilities: 'Я отвечаю на вопросы по базе знаний БАРС и указываю источники.',
  coding_task: 'Я помогаю с документацией БАРС. Написание кода и решение задач по программированию не входят в мои задачи.',
};

const replyKind = v.picklist(['greeting', 'thanks', 'farewell', 'capabilities', 'coding_task']);
type ReplyKind = v.InferOutput<typeof replyKind>;

export function chatTool(write: (kind: ReplyKind) => void) {
  return defineTool({
    name: 'reply_in_chat',
    description: 'Ответь на отдельное приветствие, благодарность, прощание или вопрос о твоих возможностях. При новом вопросе или возражении выбери подходящий инструмент вместо благодарности. Для просьбы написать код или решить задачу по программированию выбери coding_task.',
    input: v.object({ kind: replyKind }),
    run({ data }) {
      write(data.kind);
      return { output: replies[data.kind], terminate: true };
    },
  });
}

const gratitude = '(?:спасибо(?: большое| огромное)?|большое спасибо|огромное спасибо|благодарю|thanks|thank you)';
const acknowledgement = '(?:понял[аи]?|понятно|разобрал(?:ся|ась)|вс[её] (?:понятно|получилось|работает))';
const shortAcknowledgement = new RegExp(
  `^(?:${gratitude}(?:[,.!\\s]+${acknowledgement})?|(?:${acknowledgement}|да|ок(?:ей)?)(?:[,.!\\s]+${gratitude})|${acknowledgement})$`,
  'u',
);

export function isAcknowledgement(text: string): boolean {
  return shortAcknowledgement.test(text);
}

const closeRequest = '(?:закрой(?:те)?|закрывай(?:те)?|закрыть|закроем|заверши(?:те)?|завершить)(?:\\s+(?:это|мо[её]|текущее))?\\s+(?:обращение|заявку|вопрос)';
const closeOrder = new RegExp(`^(?:(?:спасибо|благодарю|вс[её] получилось)[,.!\\s]+)?(?:(?:можете|можешь|можно|давайте|давай|пожалуйста)[,\\s]+)?${closeRequest}(?:[,\\s]+(?:пожалуйста|спасибо))?$`, 'u');

export function isCloseRequest(text: string): boolean {
  return closeOrder.test(text);
}

export function renderChatReply(...values: unknown[]): string | undefined {
  for (const value of values) {
    const parsed = v.safeParse(replyKind, value);
    if (parsed.success) return replies[parsed.output];
  }
}
