import { createTelegramChannel } from '@flue/telegram';
import { Api } from 'grammy';
import { Hono } from 'hono';

import { confluenceChannel } from './channels/confluence.js';
import { githubChannel } from './channels/github.js';
import { createJiraChannel } from './channels/jira.js';
import { httpUrl, required, webhookSecret } from './config.js';
import { pool } from './db.js';
import { JiraStore } from './jira-store.js';
import { JiraWorker } from './jira-worker.js';
import { parseSupportAction, supportActionText } from './keyboards/support.js';
import { ragModel } from './rag-model.js';
import { TelegramOutput } from './telegram-output.js';
import { TelegramRequests } from './telegram-requests.js';
import { TelegramStore } from './telegram-store.js';
import { TelegramWorker } from './telegram-worker.js';

const token = required('BOT_TOKEN');
const botId = /^(\d+):[A-Za-z0-9_-]+$/.exec(token)?.[1];
if (!botId) throw new Error('Invalid BOT_TOKEN');
const client = new Api(token, {
  timeoutSeconds: 10,
  ...(process.env.TELEGRAM_API_ROOT ? { apiRoot: httpUrl('TELEGRAM_API_ROOT') } : {}),
});

const store = new TelegramStore(pool, botId);
const jiraStore = new JiraStore(pool, botId);
export const jiraWorker = new JiraWorker(jiraStore, new TelegramOutput(client, store));
const channel = createTelegramChannel({
  secretToken: webhookSecret(),
  async webhook({ update }) {
    const callback = update.callback_query;
    const action = parseSupportAction(callback?.data);
    if (callback?.message?.chat.type === 'private' && action) {
      await store.enqueue(update.update_id, callback.message.chat.id, {
        text: supportActionText[action.kind], userId: callback.from.id, supportAction: action,
        firstName: callback.from.first_name, lastName: callback.from.last_name, username: callback.from.username,
      });
      void worker.scan();
      return { method: 'answerCallbackQuery', callback_query_id: callback.id };
    }
    const message = update.message;
    const text = message?.text?.trim();
    if (!message?.from || message.chat.type !== 'private' || !text) return undefined;

    await store.enqueue(update.update_id, message.chat.id, {
      text,
      userId: message.from.id,
      firstName: message.from.first_name ?? null,
      lastName: message.from.last_name ?? null,
      username: message.from.username ?? null,
    });
    void worker.scan();
    return undefined;
  },
});

export const worker = new TelegramWorker(store, new TelegramRequests(pool, botId), client, (chatId) =>
  botId + ':' + channel.instanceId({ type: 'chat', chatId }),
);

const app = new Hono();
app.get('/health', async (c) => {
  try {
    await pool.query('SELECT 1');
    return c.json({ status: 'ok' });
  } catch {
    return c.json({ status: 'unavailable' }, 503);
  }
});
app.route('/channels/telegram', channel.route());
app.route('/channels/confluence', confluenceChannel);
app.route('/channels/github', githubChannel);
app.route('/channels/jira', createJiraChannel(jiraStore));
app.route('/internal/rag', ragModel);

export default app;
