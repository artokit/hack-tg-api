import { AgentRunError, init } from '@flue/runtime';
import { Api } from 'grammy';

import { Bars } from './agents/bars.js';
import { responseSubmission } from './db.js';
import { TelegramOutput } from './telegram-output.js';
import { type PendingUpdate, TelegramStore } from './telegram-store.js';

const unavailable = 'Сейчас не получается ответить. Попробуй ещё раз чуть позже.';

export class TelegramWorker {
  private readonly processing = new Set<string>();
  private readonly replies = new Map<string, Promise<void>>();
  private readonly output: TelegramOutput;
  private scanning = false;
  private recovered = false;
  private botUsername: string | undefined;

  constructor(
    private readonly store: TelegramStore,
    private readonly telegram: Api,
    private readonly usersApi: string,
    private readonly instanceId: (chatId: number) => string,
  ) {
    this.output = new TelegramOutput(telegram, store);
  }

  async scan(): Promise<void> {
    if (this.scanning) return;
    this.scanning = true;
    try {
      if (!this.recovered) {
        await this.store.recoverDeliveries();
        this.recovered = true;
      }
      const blockedChats = new Set<string>();
      for (const update of await this.store.pending()) {
        if (this.processing.has(update.sequence) || blockedChats.has(update.chat_id)) continue;
        this.processing.add(update.sequence);
        try {
          await this.admit(update);
        } catch (error) {
          this.processing.delete(update.sequence);
          blockedChats.add(update.chat_id);
          this.logFailure(update, error);
        }
      }
    } catch (error) {
      console.warn('Telegram queue scan failed', error instanceof Error ? error.name : 'Error');
    } finally {
      this.scanning = false;
    }
  }

  private async admit(update: PendingUpdate): Promise<void> {
    if (update.payload.text.startsWith('/')) {
      if (update.payload.commandFor) {
        this.botUsername ??= (await this.telegram.getMe()).username.toLowerCase();
        if (update.payload.commandFor !== this.botUsername) {
          this.run(update, async () => {});
          return;
        }
      }
      const answer = update.command_answer ?? await this.command(update);
      this.run(update, async () => {
        if (answer) {
          await this.output.send(`command:${update.update_id}`, update.chat_id, answer, false);
        }
      });
      return;
    }

    const id = await this.store.pinInstance(update, this.instanceId(Number(update.chat_id)));
    const agent = init(Bars, { id });
    let submission = update.submission_id;
    if (submission === null) {
      const receipt = await agent.dispatch({
        message: update.payload.text,
        idempotencyKey: `telegram:${update.update_id}`,
      });
      submission = receipt.submissionId;
      await this.store.recordSubmission(update.sequence, submission);
    }
    const submissionId = submission;

    this.run(update, async () => {
      const stopTyping = this.output.beginTyping(update.chat_id);
      let deliveryId = `submission:${submissionId}`;
      let replyText = '';
      try {
        const reply = await agent.read(submissionId);
        const responseId = reply.metadata?.telegramResponseId;
        if (typeof responseId === 'string') deliveryId = `response:${responseId}`;
        replyText = reply.text.trim();
      } catch (error) {
        if (!(error instanceof AgentRunError)) throw error;
        this.logFailure(update, error);
      } finally {
        stopTyping();
      }
      if (!replyText) deliveryId = 'failure:' + await responseSubmission(submissionId);
      await this.output.send(deliveryId, update.chat_id, replyText || unavailable, !!replyText);
    });
  }

  private runReply(update: PendingUpdate, deliver: () => Promise<void>): void {
    const previous = this.replies.get(update.chat_id) ?? Promise.resolve();
    const reply = previous.then(deliver);
    const completed = reply.catch(() => {});
    this.replies.set(update.chat_id, completed);
    this.run(update, async () => {
      try {
        await reply;
      } finally {
        if (this.replies.get(update.chat_id) === completed) this.replies.delete(update.chat_id);
      }
    });
  }

  private run(update: PendingUpdate, handle: () => Promise<void>): void {
    void handle()
      .then(() => this.store.finish(update.sequence))
      .catch((error: unknown) => this.logFailure(update, error))
      .finally(() => this.processing.delete(update.sequence));
  }

  private logFailure(update: PendingUpdate, error: unknown): void {
    console.warn('Telegram update processing failed', update.update_id,
      error instanceof Error ? error.name : 'Error');
  }

  private async command(update: PendingUpdate): Promise<string> {
    const { text, userId, username, firstName, lastName } = update.payload;
    const [token, argument] = text.split(/\s+/);
    let answer: string;
    switch (token.split('@')[0].toLowerCase()) {
      case '/reset':
        return await this.store.reset(update, this.instanceId(Number(update.chat_id)));
      case '/start':
        try {
          const existing = await fetch(`${this.usersApi}/users/by-telegram-id/${userId}`, {
            signal: AbortSignal.timeout(5_000),
          });
          if (existing.status === 404) {
            const response = await fetch(`${this.usersApi}/users`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ telegram_user_id: userId, username: username ?? null }),
              signal: AbortSignal.timeout(5_000),
            });
            if (!response.ok && response.status !== 409) {
              throw new Error(`Users API status ${response.status}`);
            }
          } else if (!existing.ok) {
            throw new Error(`Users API status ${existing.status}`);
          }
          const name = [firstName, lastName].filter(Boolean).join(' ');
          answer = `Привет, ${name}!\nНапиши свой вопрос. Чтобы начать новый диалог, отправь /reset.`;
        } catch {
          answer = 'Сейчас не получается зарегистрироваться. Попробуй чуть позже.';
        }
        break;
      case '/me':
        answer = await this.lookupUser(argument);
        break;
      default:
        answer = '';
    }
    return await this.store.commandAnswer(update.sequence, answer);
  }

  private async lookupUser(argument: string | undefined): Promise<string> {
    if (!argument || !/^\d{1,10}$/.test(argument)) return 'Укажи id: /me <id>';
    const id = Number(argument);
    try {
      const response = await fetch(`${this.usersApi}/users/${id}`, {
        signal: AbortSignal.timeout(5_000),
      });
      if (response.status === 404) return `Пользователь с id ${id} не найден`;
      if (!response.ok) throw new Error(`Users API status ${response.status}`);
      const user = await response.json() as {
        id: number;
        telegram_user_id: number;
        username: string | null;
      };
      return `id: ${user.id}\ntelegram_user_id: ${user.telegram_user_id}\nusername: ${user.username || '—'}`;
    } catch {
      return 'Сейчас не получается получить пользователя. Попробуй чуть позже.';
    }
  }
}
