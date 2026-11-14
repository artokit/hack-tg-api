import { createTelegramChannel } from '@flue/telegram';
import { Api } from 'grammy';
import { Hono } from 'hono';

import { httpUrl, required, webhookSecret } from './config.js';
import { pool } from './db.js';
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
const channel = createTelegramChannel({
  secretToken: webhookSecret(),
  async webhook({ update }) {
    const message = update.message;
    const text = message?.text?.trim();
    if (!message?.from || message.chat.type !== 'private' || !text) return undefined;

    const commandFor = /^\/[^\s@]+@([^\s]+)/.exec(text)?.[1].toLowerCase();
    await store.enqueue(update.update_id, message.chat.id, {
      text,
      userId: message.from.id,
      firstName: message.from.first_name,
      lastName: message.from.last_name,
      username: message.from.username,
      commandFor,
    });
    void worker.scan();
    return undefined;
  },
});

export const worker = new TelegramWorker(store, client, (chatId) =>
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

export default app;
