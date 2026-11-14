import assert from 'node:assert/strict';
import { spawn, type ChildProcess } from 'node:child_process';
import { createServer, type Server } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import { test } from 'node:test';

import pg from 'pg';

import { splitReply } from '../src/telegram-output.js';

test('plain-text fallback preserves Unicode at Telegram message boundaries', () => {
  const text = 'а'.repeat(4095) + '🙂' + 'б'.repeat(4097);
  const parts = splitReply(text);
  assert.equal(parts.join(''), text);
  assert.equal(parts[0].length, 4095);
  assert.ok(parts.every((part) => part.length <= 4096));
});

function listen(server: Server): Promise<string> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      assert.ok(address && typeof address !== 'string');
      resolve(`http://127.0.0.1:${address.port}`);
    });
  });
}

async function until<T>(check: () => T | Promise<T>, label: string, timeout = 12_000): Promise<NonNullable<T>> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await delay(40);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

test('verified Telegram webhook, response steering, durable delivery and reset', {
  skip: !process.env.TEST_FLUE_DATABASE_URL && 'Set TEST_FLUE_DATABASE_URL to a disposable PostgreSQL database',
  timeout: 100_000,
}, async () => {
  const connectionString = process.env.TEST_FLUE_DATABASE_URL;
  const database = new pg.Pool({ connectionString });
  const botId = String(Date.now());
  const chatId = 10042;
  const secret = 'integration-secret';
  const calls: { method: string; text?: string }[] = [];
  const requests: { messages: { role: string; content: unknown }[] }[] = [];
  let authorization: string | undefined;
  let releaseModel: (() => void) | undefined;
  let blockModel = false;
  let run: ChildProcess | undefined;
  let serverLogs = '';

  const mock = createServer(async (req, res) => {
    try {
      const path = req.url ?? '';
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
      if (path.endsWith('/chat/completions')) {
        authorization = req.headers.authorization;
        requests.push(body);
        const held = blockModel;
        if (held) {
          blockModel = false;
          await new Promise<void>((resolve) => { releaseModel = resolve; });
        }
        const text = body.messages.filter((message: { role: string }) => message.role === 'user')
          .map((message: { content: unknown }) => typeof message.content === 'string'
            ? message.content : Array.isArray(message.content)
              ? message.content.map((part) => part.text ?? '').join('') : '').join(' / ');
        res.writeHead(200, { 'content-type': 'text/event-stream' });
        const message = { id: 'chatcmpl-test', object: 'chat.completion.chunk', created: 1, model: 'test' };
        res.write(`data: ${JSON.stringify({
          ...message, choices: [{ index: 0, delta: { role: 'assistant', content: `**${text}**` }, finish_reason: null }],
        })}\n\n`);
        res.end(`data: ${JSON.stringify({
          ...message, choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
          usage: { prompt_tokens: 50, completion_tokens: 10, total_tokens: 60 },
        })}\n\ndata: [DONE]\n\n`);
        return;
      }
      if (path.startsWith(`/bot${botId}:`)) {
        const method = path.split('/').at(-1)!;
        if (method === 'getMe') {
          res.end(JSON.stringify({ ok: true, result: { id: Number(botId), is_bot: true, username: 'test_bot' } }));
          return;
        }
        calls.push({ method, text: body.rich_message?.markdown ?? body.text });
        res.end(JSON.stringify({ ok: true, result: method === 'sendChatAction' ? true : { message_id: calls.length } }));
        return;
      }
      res.writeHead(404).end();
    } catch {
      res.writeHead(500).end();
    }
  });

  try {
    const mockUrl = await listen(mock);
    const reservation = createServer();
    const appUrl = await listen(reservation);
    await new Promise<void>((resolve) => reservation.close(() => resolve()));

    const start = async () => {
      run = spawn(process.execPath, ['dist/server.js'], {
        env: {
          ...process.env,
          BOT_TOKEN: `${botId}:test`,
          TELEGRAM_WEBHOOK_SECRET_TOKEN: secret,
          TELEGRAM_API_ROOT: mockUrl,
          FLUE_DATABASE_URL: connectionString,
          PORT: new URL(appUrl).port,
          CHAT_BASE_URL: `${mockUrl}/v1`,
          CHAT_API_KEY: '',
          CHAT_MODEL: 'test',
          CHAT_CONTEXT_WINDOW: '8192',
        },
      });
      run.stdout?.on('data', (chunk) => { serverLogs += chunk; });
      run.stderr?.on('data', (chunk) => { serverLogs += chunk; });
      await until(async () => {
        if (run?.exitCode != null) throw new Error(serverLogs);
        return await fetch(`${appUrl}/health`).then((r) => r.ok).catch(() => false);
      }, 'Flue health');
    };
    const stop = async () => {
      const child = run;
      if (!child || child.exitCode !== null || child.signalCode !== null) return;
      await new Promise<void>((resolve) => {
        child.once('exit', () => resolve());
        child.kill('SIGKILL');
      });
    };
    const send = (update_id: number, text: string, suppliedSecret = secret) =>
      fetch(`${appUrl}/channels/telegram/webhook`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': suppliedSecret },
        body: JSON.stringify({
          update_id,
          message: {
            message_id: update_id, date: 0, chat: { id: chatId, type: 'private', first_name: 'Tester' },
            from: { id: chatId, is_bot: false, first_name: 'Tester', username: 'tester' }, text,
          },
        }),
      });
    const sent = (method: string, text: string) =>
      calls.find((call) => call.method === method && call.text?.includes(text));
    const pending = async () => {
      const result = await database.query(
        'SELECT 1 FROM bars_telegram_updates WHERE bot_id = $1 AND finished_at IS NULL', [botId],
      );
      return result.rows.length;
    };

    await start();
    assert.equal((await send(1, '/start', 'wrong-secret')).status, 401);
    assert.equal((await send(1, '/start')).status, 200);
    assert.equal((await send(1, '/start')).status, 200);
    await until(() => sent('sendMessage', 'Привет'), 'greeting');
    assert.equal(requests.length, 0);

    blockModel = true;
    assert.equal((await send(3, 'первый')).status, 200);
    await until(() => releaseModel, 'live model request');
    assert.equal((await send(4, 'уточнение')).status, 200);
    assert.equal((await send(4, 'уточнение')).status, 200);
    assert.equal((await send(5, '/reset')).status, 200);
    await until(() => sent('sendMessage', 'ещё отвечаю'), 'busy reset');
    await until(() => calls.some((call) => call.method === 'sendChatAction'), 'typing action');
    releaseModel?.();
    await until(() => sent('sendRichMessage', 'первый / уточнение'), 'one joined rich reply');
    await until(async () => !await pending(), 'update settlement');
    assert.equal(calls.filter((call) => call.method === 'sendRichMessage').length, 1);
    assert.equal(authorization, undefined);

    blockModel = true;
    assert.equal((await send(6, 'до перезапуска')).status, 200);
    await until(() => requests.some((request) => JSON.stringify(request).includes('до перезапуска')), 'pending submission');
    await until(async () => (await database.query(
      'SELECT submission_id FROM bars_telegram_updates WHERE bot_id = $1 AND update_id = 6', [botId],
    )).rows[0]?.submission_id, 'saved Flue receipt');
    await stop();
    releaseModel?.();
    await start();
    await until(() => sent('sendRichMessage', 'до перезапуска'), 'recovered submission', 50_000);
    await until(async () => !await pending(), 'recovery settlement');

    const beforeReset = requests.length;
    assert.equal((await send(7, '/reset')).status, 200);
    await until(() => sent('sendMessage', 'Диалог сброшен'), 'reset');
    assert.equal(requests.length, beforeReset);
    assert.equal((await send(8, 'новый вопрос')).status, 200);
    await until(() => sent('sendRichMessage', '**новый вопрос**'), 'new conversation');
    await until(async () => !await pending(), 'final settlement');
    assert.equal(calls.filter((call) => call.text?.includes('Привет')).length, 1);
    assert.equal(JSON.stringify(requests.at(-1)).includes('первый'), false);
  } catch (error) {
    console.error(serverLogs, calls);
    throw error;
  } finally {
    releaseModel?.();
    if (run?.exitCode === null && run.signalCode === null) {
      const child = run;
      await new Promise<void>((resolve) => {
        child.once('exit', () => resolve());
        child.kill('SIGKILL');
      });
    }
    mock.closeAllConnections();
    await new Promise<void>((resolve) => mock.close(() => resolve()));
    await database.end();
  }
});
