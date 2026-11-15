import { AgentRunError, init } from '@flue/runtime';
import { type FSMFlavor, type StateSession, stateMiddleware } from '@kalutskii/grammy-fsm';
import { type Api, type SessionFlavor, Composer, Context } from 'grammy';

import { Bars } from './agents/bars.js';
import { responseSubmission } from './db.js';
import { acceptInvite, accessDenied, accessGranted, isEmployee } from './employees-api.js';
import { recordDelivery, recordReplyDuration } from './telemetry.js';
import { renderChatReply } from './telegram-chat.js';
import { renderRag } from './telegram-rag.js';
import { TelegramOutput } from './telegram-output.js';
import { type PendingUpdate, TelegramStore } from './telegram-store.js';

const unavailable = 'Сейчас не получается ответить. Попробуй ещё раз чуть позже.';
const inviteIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type UpdateContext = Context & SessionFlavor<StateSession> & FSMFlavor & {
  pending: PendingUpdate;
  employee: boolean;
  answer: string | null;
};

export class TelegramWorker {
  private readonly processing = new Set<string>();
  private readonly replies = new Map<string, Promise<void>>();
  private readonly output: TelegramOutput;
  private readonly handlers = new Composer<UpdateContext>();
  private scanning = false;
  private recovered = false;
  private botInfo: Context['me'] | undefined;

  constructor(
    private readonly store: TelegramStore,
    private readonly telegram: Api,
    private readonly instanceId: (chatId: number) => string,
  ) {
    this.output = new TelegramOutput(telegram, store);
    this.handlers.use(stateMiddleware());
    this.handlers.command('start', async (ctx) => {
      const [argument] = ctx.match.split(/\s+/, 1);
      await ctx.fsm.clear();
      if (argument) {
        const inviteId = argument.replace(/^invite_/, '');
        if (!inviteIdPattern.test(inviteId)) {
          await this.answer(ctx, accessDenied);
          return;
        }
        const accepted = ctx.employee
          || await acceptInvite(inviteId, ctx.pending.payload)
          || await isEmployee(ctx.pending.payload);
        await this.answer(ctx, accepted ? accessGranted : accessDenied);
        return;
      }
      await this.answer(ctx, ctx.employee ? 'Можешь задавать вопросы.' : accessDenied);
    });
    this.handlers.command('reset', async (ctx) => {
      if (!ctx.employee) {
        await ctx.fsm.clear();
        await this.answer(ctx, accessDenied);
        return;
      }
      ctx.answer = await this.store.reset(ctx.pending, this.instanceId(ctx.chatId));
    });
    this.handlers.on('message:entities:bot_command', (ctx) => { ctx.answer = ''; });
  }

  async scan(): Promise<void> {
    if (this.scanning) return;
    this.scanning = true;
    try {
      if (!this.recovered) {
        for (const kind of await this.store.recoverDeliveries()) recordDelivery(kind, 'unknown');
        this.recovered = true;
      }
      const blockedChats = new Set<string>();
      for (const update of await this.store.pending()) {
        if (this.processing.has(update.sequence) || blockedChats.has(update.chat_id)) continue;
        this.processing.add(update.sequence);
        try {
          await this.store.startProcessing(update.sequence);
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
    const employee = await isEmployee(update.payload);
    const answer = update.command_answer ?? (update.instance_id === null
      ? await this.handle(update, employee) : null);
    const response = answer ?? (!employee ? accessDenied : null);
    if (response !== null) {
      this.run(update, async () => {
        if (response) {
          await this.output.send(`command:${update.update_id}`, update.chat_id, response, 'service', false);
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
      let replyHtml: string | undefined;
      let available = true;
      try {
        const reply = await agent.read(submissionId);
        const responseId = reply.metadata?.telegramResponseId;
        if (typeof responseId === 'string') deliveryId = `response:${responseId}`;
        const ragResults = reply.data.ragAnswer;
        if (ragResults?.length) {
          const rendered = renderRag(...ragResults);
          replyText = rendered.text;
          replyHtml = rendered.html;
          available = rendered.available;
        } else {
          replyText = renderChatReply(...(reply.data.chatAnswer ?? [])) ?? '';
        }
      } catch (error) {
        if (!(error instanceof AgentRunError)) throw error;
        this.logFailure(update, error);
      } finally {
        stopTyping();
      }
      if (!replyText) deliveryId = 'failure:' + await responseSubmission(submissionId);
      const kind = replyText && available ? 'answer' : 'fallback';
      const delivery = await this.output.send(deliveryId, update.chat_id, replyText || unavailable, kind, !!replyText, replyHtml);
      if (kind === 'answer' && delivery?.status === 'sent') {
        try {
          const timing = await this.store.replyTiming(await responseSubmission(submissionId));
          if (timing?.received_at && timing.processing_at) {
            recordReplyDuration(timing.received_at, timing.processing_at, delivery.startedAt, delivery.finishedAt);
          }
        } catch (error) {
          console.warn('Telegram timing unavailable', error instanceof Error ? error.name : 'Error');
        }
      }
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

  private async answer(ctx: UpdateContext, text: string): Promise<void> {
    ctx.answer = await this.store.commandAnswer(ctx.pending, text, ctx.session);
  }

  private async handle(update: PendingUpdate, employee: boolean): Promise<string | null> {
    const { text, userId, firstName, lastName, username } = update.payload;
    const session = await this.store.session(update.chat_id);
    const [token] = text.startsWith('/') ? text.split(/\s+/, 1) : [];
    if (!token && session._state === null) return null;
    this.botInfo ??= await this.telegram.getMe();
    const ctx = new Context({
      update_id: Number(update.update_id),
      message: {
        message_id: 0,
        date: 0,
        chat: { type: 'private', id: Number(update.chat_id), first_name: firstName ?? '' },
        from: {
          id: userId,
          is_bot: false,
          first_name: firstName ?? '',
          last_name: lastName ?? undefined,
          username: username ?? undefined,
        },
        text: token ? token.toLowerCase() + text.slice(token.length) : text,
        entities: token ? [{ type: 'bot_command', offset: 0, length: token.length }] : undefined,
      },
    }, this.telegram, this.botInfo);
    const routed = Object.assign(ctx, { pending: update, employee, session, answer: null }) as UpdateContext;
    await this.handlers.middleware()(routed, async () => {});
    return routed.answer;
  }
}
