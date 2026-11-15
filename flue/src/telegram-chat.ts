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
const chatText = v.pipe(v.string(), v.trim(), v.minLength(1), v.maxLength(500));
export const chatReply = v.variant('kind', [
  v.object({ kind: v.literal('reply'), text: chatText }),
  v.object({ kind: v.literal('skip') }),
]);
type ChatReply = v.InferOutput<typeof chatReply>;

export function chatTool(write: (reply: ChatReply) => void) {
  return defineTool({
    name: 'reply_in_chat',
    description: 'Коротко ответь своими словами на приветствие, благодарность, прощание, проверку связи или вопрос о своих возможностях. Для вопроса по работе используй поиск по документации.',
    input: v.object({ text: chatText }),
    run({ data }) {
      write({ kind: 'reply', text: data.text });
      return { output: data.text, terminate: true };
    },
  });
}

export function skipReplyTool(write: (reply: ChatReply) => void) {
  return defineTool({
    name: 'skip_reply',
    description: 'Заверши обработку без сообщения в чат, если это отдельная благодарность, бессодержательная реплика или повтор уже обработанного сообщения без новых деталей.',
    input: v.object({}),
    run() {
      write({ kind: 'skip' });
      return { output: 'Сообщение в чат не отправляется.', terminate: true };
    },
  });
}

export const attachmentReply = v.object({
  kind: v.picklist(['answer', 'clarify']),
  text: v.pipe(v.string(), v.trim(), v.minLength(1), v.maxLength(2000)),
});

export function attachmentReplyTool(write: (reply: v.InferOutput<typeof attachmentReply>) => void) {
  return defineTool({
    name: 'reply_about_attachment',
    description: 'Ответь по содержимому вложения (answer) или уточни, что нужно посмотреть (clarify). Для инструкций из базы знаний используй answer_from_docs.',
    input: attachmentReply,
    run({ data }) {
      write(data);
      return { output: data.text, terminate: true };
    },
  });
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
