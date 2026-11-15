import { AgentRunError, init } from '@flue/runtime';
import { type FSMFlavor, type StateSession, stateMiddleware } from '@kalutskii/grammy-fsm';
import { type Api, type SessionFlavor, Composer, Context } from 'grammy';

import { Bars } from './agents/bars.js';
import { SupportRequestFinalizer } from './agents/support-request-finalizer.js';
import { responseSubmission } from './db.js';
import { acceptInvite, accessDenied, accessGranted, isEmployee } from './employees-api.js';
import { getSupportKeyboard, type SupportButtons } from './keyboards/support.js';
import { getSupportTicketUrl } from './support-api.js';
import { recordDelivery, recordReplyDuration } from './telemetry.js';
import { isAcknowledgement, isCloseRequest, renderChatReply } from './telegram-chat.js';
import { type ClosedRequest, type CloseReason, isOperatorRequest, supportRequestClosed } from './support-request.js';
import { renderRag, supportRagReply } from './telegram-rag.js';
import { type DeliveryResult, TelegramOutput } from './telegram-output.js';
import { type ActiveRequest, type RequestPhase, TelegramRequests } from './telegram-requests.js';
import { type DeliveryKind, type PendingUpdate, resetAnswer, TelegramStore } from './telegram-store.js';

const unavailable = 'Сейчас не получается ответить. Попробуйте чуть позже.';
const feedbackQuestion = 'Удалось решить вопрос?';
const detailsQuestion = 'Что осталось нерешённым?';
const closeQuestion = 'Закрыть обращение или продолжим?';
const closedAnswer = 'Обращение закрыто.';
const handoffAnswer = 'Передаю вопрос специалисту.';
const inviteIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const timeoutReasons = {
  feedback: 'feedback_timeout',
  clarification: 'clarification_timeout',
  details: 'details_timeout',
  technical: 'technical_timeout',
  handoff_confirmation: 'clarification_timeout',
  close_confirmation: 'clarification_timeout',
} satisfies Record<Exclude<RequestPhase, 'answer'>, CloseReason>;

function shortReply(text: string): string {
  return text.normalize('NFKC').toLowerCase().replace(/^[\s\p{P}]+|[\s\p{P}\p{Extended_Pictographic}]+$/gu, '');
}

function closeAcknowledgement(reason: CloseReason | undefined): string | undefined {
  if (reason === 'thanks') return `Пожалуйста! ${closedAnswer}`;
  if (reason === 'confirmed' || reason === 'user_closed') return closedAnswer;
  if (reason === 'operator_requested') return handoffAnswer;
}

type UpdateContext = Context & SessionFlavor<StateSession> & FSMFlavor & {
  pending: PendingUpdate;
  employee: boolean;
  answer: string | null;
};

export class TelegramWorker {
  private readonly processing = new Set<string>();
  private readonly replies = new Map<string, Promise<void>>();
  private readonly finalizing = new Set<string>();
  private readonly output: TelegramOutput;
  private readonly handlers = new Composer<UpdateContext>();
  private scanning = false;
  private recovered = false;
  private botInfo: Context['me'] | undefined;

  constructor(
    private readonly store: TelegramStore,
    private readonly requests: TelegramRequests,
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
      await this.answer(ctx, ctx.employee ? renderChatReply('greeting')! : accessDenied);
    });
    this.handlers.command('reset', async (ctx) => {
      if (!ctx.employee) {
        await ctx.fsm.clear();
        await this.answer(ctx, accessDenied);
        return;
      }
      await ctx.fsm.clear();
      await this.answer(ctx, resetAnswer);
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
      await this.processDeadlines();
      for (const { outcome, finalizer_attempt } of await this.requests.finalizations()) {
        if (this.finalizing.has(outcome.request_id)) continue;
        this.finalizing.add(outcome.request_id);
        void this.finalize(outcome, finalizer_attempt);
      }
      const blockedChats = new Set<string>();
      for (const update of await this.store.pending()) {
        if (this.processing.has(update.sequence) || this.replies.has(update.chat_id) || blockedChats.has(update.chat_id)) continue;
        this.processing.add(update.sequence);
        try {
          await this.store.startProcessing(update.sequence);
          await this.runReply(update.chat_id, () => this.admit(update));
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
      if (response === resetAnswer) {
        const active = await this.requests.active(update.chat_id);
        if (active && BigInt(active.latest_sequence) < BigInt(update.sequence)) {
          await this.requests.close(active, active.latest_sequence, 'reset');
        }
      }
      this.run(update, async () => {
        if (response) {
          await this.output.send(`command:${update.update_id}`, update.chat_id, response, 'service', false);
        }
      });
      return;
    }

    const legacy = update.instance_id !== null && update.request_id === null;
    const request = legacy ? undefined : await this.acceptForRequest(update);
    if (!legacy && !request) return;
    const id = request?.instance_id ?? update.instance_id;
    if (!id) throw new Error('Missing Telegram request instance');
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
      let replyImages: string[] | undefined;
      let phase: RequestPhase = 'technical';
      let followUp: string | undefined;
      let buttons: SupportButtons | undefined;
      let available = true;
      try {
        const reply = await agent.read(submissionId);
        const responseId = reply.metadata?.telegramResponseId;
        if (typeof responseId === 'string') deliveryId = `response:${responseId}`;
        const ragResults = reply.data.ragAnswer;
        if (ragResults?.length) {
          const rendered: ReturnType<typeof supportRagReply> = request
            ? supportRagReply(ragResults, request.phase)
            : { ...renderRag(...ragResults), phase: 'answer' };
          phase = rendered.phase;
          followUp = rendered.followUp;
          if (rendered.offerSupport) buttons = 'operator';
          replyText = rendered.text;
          replyHtml = rendered.html;
          replyImages = rendered.images;
          available = rendered.available;
        } else if (!replyText) {
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
      if (!request) {
        const receipt = await this.output.send(
          deliveryId, update.chat_id, replyText || unavailable, kind, !!replyText, replyHtml, replyImages,
        );
        if (kind === 'answer') await this.recordReplyTiming(submissionId, receipt);
        return;
      }
      await this.runReply(update.chat_id, async () => {
        const active = await this.requests.active(update.chat_id);
        if (active?.id !== request.id) return;
        const receipt = await this.deliver(request, deliveryId, replyText || unavailable, {
          sequence: update.sequence, phase: followUp ? undefined : phase,
          html: replyHtml, rich: !!replyText, kind, images: replyImages, buttons: followUp ? undefined : buttons,
        });
        if (followUp && receipt.status === 'sent') {
          const next = await this.deliver(request, `${deliveryId}:follow-up`, followUp, {
            sequence: update.sequence, phase, buttons, optional: true,
          });
          if (next.status !== 'sent' && receipt.sent_at) {
            await this.requests.advance(request, update.sequence, 'technical', receipt.sent_at);
          }
        }
        if (kind === 'answer') await this.recordReplyTiming(submissionId, receipt);
      });
    });
  }

  private async recordReplyTiming(submissionId: string, receipt: DeliveryResult): Promise<void> {
    if (receipt.status !== 'sent' || receipt.startedAt === undefined || receipt.finishedAt === undefined) return;
    try {
      const responseId = await responseSubmission(submissionId);
      const timing = await this.store.replyTiming(responseId);
      if (timing?.received_at && timing.processing_at) {
        recordReplyDuration(responseId, timing.received_at, timing.processing_at, receipt.startedAt, receipt.finishedAt);
      }
    } catch (error) {
      console.warn('Telegram timing unavailable', error instanceof Error ? error.name : 'Error');
    }
  }

  private async acceptForRequest(update: PendingUpdate): Promise<ActiveRequest | undefined> {
    const text = shortReply(update.payload.text);
    const thanks = isAcknowledgement(text);
    const close = isCloseRequest(text);
    const action = update.payload.supportAction;
    const current = await this.requests.active(update.chat_id);
    if (update.request_id && current?.id !== update.request_id) {
      const reason = await this.requests.closedBy(update);
      this.sendService(update, 'closed', closeAcknowledgement(reason));
      return;
    }
    const previous = update.request_phase ?? current?.phase;
    if (action && (current?.id !== action.requestId
      || current.latest_sequence !== (update.request_id ? update.sequence : action.sequence)
      || (action.kind === 's'
        ? previous !== 'details' && previous !== 'handoff_confirmation'
        : action.kind === 'n' ? previous !== 'feedback'
          : action.kind === 'c' ? previous !== 'close_confirmation'
            : previous !== 'feedback' && previous !== 'close_confirmation'))) {
      this.sendService(update, 'chat');
      return;
    }
    const greeting = /^(?:привет|здравствуйте|добрый день)$/u.test(text);
    if (!current && (close || thanks || greeting)) {
      this.sendService(update, 'chat', close ? 'У вас нет открытого обращения.'
        : renderChatReply(thanks ? 'thanks' : 'greeting'));
      return;
    }
    const request = await this.requests.pin(update, this.instanceId(Number(update.chat_id)));
    if (!request) {
      this.run(update, async () => {});
      return;
    }
    const markingSolved = request.phase === 'feedback';
    const confirmingClose = request.phase === 'close_confirmation';
    const confirmingHandoff = request.phase === 'handoff_confirmation';
    const handoff = action?.kind === 's' || isOperatorRequest(text)
      || (confirmingHandoff && /^(?:да|да,? передайте|да,? передай|да,? пожалуйста)$/u.test(text));
    const declinedHandoff = confirmingHandoff && /^(?:нет|нет,? спасибо)$/u.test(text);
    const yes = (markingSolved || confirmingClose) && /^(?:да|да,? закрыть)$/u.test(text);
    const no = (markingSolved || confirmingClose) && /^(?:нет|нет,? (?:нужна помощь|продолжим))$/u.test(text);
    const answered = request.phase === 'answer' || markingSolved;
    await this.requests.append(
      request, `user:${update.update_id}`, 'user', update.received_at,
      thanks || close || yes || no || handoff || declinedHandoff || action ? update.payload.text : null, update.sequence,
    );
    const reason = close || (yes && confirmingClose) ? 'user_closed'
      : handoff ? 'operator_requested' : yes ? 'confirmed' : thanks && answered ? 'thanks' : undefined;
    if (reason) {
      const draft = reason === 'operator_requested' ? {
        title: 'Требуется помощь специалиста',
        description: 'Сотрудник попросил передать обращение специалисту. Детали есть в переписке.',
      } : undefined;
      const closed = await this.requests.close(request, update.sequence, reason, draft);
      this.sendService(update, 'closed', closed ? closeAcknowledgement(reason) : undefined);
      return;
    }
    await this.requests.clearDeadline(request, update.sequence);
    if (thanks || no || declinedHandoff) {
      const prompt = thanks
        ? { text: closeQuestion, phase: 'close_confirmation', buttons: 'close' } as const
        : declinedHandoff
          ? { text: 'Хорошо. Если появятся новые детали, напишите.', phase: 'clarification', buttons: undefined } as const
          : { text: detailsQuestion, phase: 'details', buttons: 'operator' } as const;
      this.run(update, () => this.runReply(update.chat_id, async () => {
        await this.deliver(request, `prompt:${update.update_id}`, prompt.text, {
          sequence: update.sequence, phase: prompt.phase, buttons: prompt.buttons,
        });
      }));
      return;
    }
    return request;
  }

  private sendService(update: PendingUpdate, prefix: string, text?: string): void {
    this.run(update, () => this.runReply(update.chat_id, async () => {
      if (text) await this.output.send(`${prefix}:${update.update_id}`, update.chat_id, text, 'service', false);
    }));
  }

  private async deliver(
    request: ActiveRequest, id: string, text: string,
    next?: {
      sequence?: string; phase?: RequestPhase; rich?: boolean; html?: string;
      kind?: DeliveryKind; images?: string[]; buttons?: SupportButtons; optional?: boolean;
    },
  ): Promise<DeliveryResult> {
    const keyboard = next?.buttons && next.sequence
      ? getSupportKeyboard(next.buttons, request.id, next.sequence) : undefined;
    const receipt = await this.output.send(
      id, request.chat_id, text, next?.kind ?? 'service', next?.rich ?? false, next?.html, next?.images, keyboard,
    );
    if (receipt.status !== 'sent' || !receipt.sent_at) {
      if (next?.sequence && !next.optional) await this.requests.close(request, next.sequence, 'delivery_failed');
      return receipt;
    }
    await this.requests.append(request, id, 'assistant', receipt.sent_at, text);
    if (next?.sequence && next.phase) {
      await this.requests.advance(request, next.sequence, next.phase, receipt.sent_at);
    }
    return receipt;
  }

  private async processDeadlines(): Promise<void> {
    for (const request of await this.requests.due()) {
      if (this.replies.has(request.chat_id)) continue;
      void this.runReply(request.chat_id, async () => {
        const [due] = await this.requests.due(request.id);
        if (!due) return;
        if (due.phase === 'answer') {
          await this.deliver(due, `feedback:${due.id}:${due.latest_sequence}`, feedbackQuestion, {
            sequence: due.latest_sequence, phase: 'feedback', buttons: 'feedback',
          });
        } else {
          await this.requests.close(due, due.latest_sequence, timeoutReasons[due.phase], undefined, true);
        }
      }).catch((error: unknown) => {
        console.warn('Telegram request deadline failed', request.id, error instanceof Error ? error.name : 'Error');
      });
    }
  }

  private async finalize(outcome: ClosedRequest, attempt: number): Promise<void> {
    const id = outcome.request_id;
    try {
      const finalizer = init(SupportRequestFinalizer, { id });
      const receipt = await finalizer.dispatch({
        message: { kind: 'signal', type: supportRequestClosed, body: JSON.stringify(outcome) },
        idempotencyKey: `support-request:${id}:${attempt}`,
      });
      await finalizer.read(receipt);
      if (outcome.handoff) {
        const url = await getSupportTicketUrl(id);
        const chatId = outcome.telegram_chat_id;
        await this.runReply(chatId, async () => {
          await this.output.send(`ticket-created:${id}`, chatId, `Заявка создана в Jira.\n${url}`, 'service', false);
        });
      }
      await this.requests.finalized(id);
    } catch (error) {
      console.warn('Telegram request finalization failed', id, error instanceof Error ? error.name : 'Error');
      await this.requests.retryFinalization(id, error instanceof AgentRunError).catch(() => {});
    } finally {
      this.finalizing.delete(id);
    }
  }

  private async runReply(chatId: string, deliver: () => Promise<void>): Promise<void> {
    const previous = this.replies.get(chatId) ?? Promise.resolve();
    const reply = previous.then(deliver);
    const completed = reply.catch(() => {});
    this.replies.set(chatId, completed);
    try {
      await reply;
    } finally {
      if (this.replies.get(chatId) === completed) this.replies.delete(chatId);
    }
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
