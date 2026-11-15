import { defineTool } from '@flue/runtime';
import * as v from 'valibot';

const replies = {
  greeting: 'Привет! Чем могу помочь по документации БАРС?',
  thanks: 'Пожалуйста!',
  farewell: 'До встречи!',
  capabilities: 'Я отвечаю на вопросы по базе знаний БАРС и указываю источники.',
};

const replyKind = v.picklist(['greeting', 'thanks', 'farewell', 'capabilities']);
type ReplyKind = v.InferOutput<typeof replyKind>;

export function chatTool(write: (kind: ReplyKind) => void) {
  return defineTool({
    name: 'reply_in_chat',
    description: 'Ответь на приветствие, благодарность, прощание или вопрос о твоих возможностях. Если в сообщении есть содержательный запрос, вызывай answer_from_docs, даже если сообщение начинается с приветствия.',
    input: v.object({ kind: replyKind }),
    run({ data }) {
      write(data.kind);
      return { output: replies[data.kind], terminate: true };
    },
  });
}

export function renderChatReply(...values: unknown[]): string | undefined {
  for (const value of values) {
    const parsed = v.safeParse(replyKind, value);
    if (parsed.success) return replies[parsed.output];
  }
}
