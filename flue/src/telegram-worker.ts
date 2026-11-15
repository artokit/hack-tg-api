import { AgentRunError, type DeliveredMessageInput, init } from '@flue/runtime';
import { type FSMFlavor, type StateSession, stateMiddleware } from '@kalutskii/grammy-fsm';
import { type Api, type SessionFlavor, Composer, Context } from 'grammy';
import * as v from 'valibot';

import { Bars } from './agents/bars.js';
import { saveSupportRequestOutcome, SupportRequestFinalizer } from './agents/support-request-finalizer.js';
import { bannedMessage, banUser, UserBannedError } from './bans-api.js';
import { responseSubmission } from './db.js';
import { acceptInvite, accessDenied, accessGranted, inviteExpired, isEmployee } from './employees-api.js';
import { getSupportKeyboard, type SupportButtons } from './keyboards/support.js';
import { getSupportTicketUrl } from './support-api.js';
import { recordDelivery, recordReplyDuration } from './telemetry.js';
import { attachmentSummary, loadAttachment } from './telegram-attachments.js';
import { attachmentReply, chatReply, isCloseRequest, renderChatReply } from './telegram-chat.js';
import { type ClosedRequest, type CloseReason, isOperatorRequest, type ReplyFlags, type SupportAction, supportAction, supportRequestClosed } from './support-request.js';
import { renderRag, supportRagReply } from './telegram-rag.js';
import { type DeliveryResult, TelegramOutput } from './telegram-output.js';
import { type ActiveRequest, type RequestPhase, TelegramRequests } from './telegram-requests.js';
import { telegramTextDelivery } from './telegram-spam.js';
import { type DeliveryKind, type PendingUpdate, TelegramStore } from './telegram-store.js';

const unavailable = 'Сейчас не получается ответить. Попробуйте чуть позже.';
const closeQuestion = 'Закрыть обращение?';
const detailsQuestion = 'Что осталось нерешённым?';
const closedAnswer = 'Обращение закрыто.';
const handoffAnswer = 'Передаю вопрос специалисту.';
const inviteIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const timeoutReasons = {
  answer: 'feedback_timeout',
  feedback: 'feedback_timeout',
  clarification: 'clarification_timeout',
  details: 'details_timeout',
  technical: 'technical_timeout',
  handoff_confirmation: 'clarification_timeout',
  close_confirmation: 'clarification_timeout',
} satisfies Record<RequestPhase, CloseReason>;

function shortReply(text: string): string {
  return text.normalize('NFKC').toLowerCase().replace(/^[\s\p{P}]+|[\s\p{P}\p{Extended_Pictographic}]+$/gu, '');
}

function closeAcknowledgement(reason: CloseReason | undefined): string | undefined {
  if (reason === 'thanks') return `Пожалуйста! ${closedAnswer}`;
  if (reason === 'confirmed' || reason === 'user_closed' || reason === 'user_requested') return closedAnswer;
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
  private attachmentAdmissions = 0;
  private nextSpamCleanup = 0;
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
        const invite = ctx.employee ? 'accepted' : await acceptInvite(inviteId, ctx.pending.payload);
        const accepted = invite === 'accepted' || await isEmployee(ctx.pending.payload);
        const denied = invite === 'expired' ? inviteExpired : accessDenied;
        await this.answer(ctx, accepted ? accessGranted : denied);
        return;
      }
      await this.answer(ctx, ctx.employee ? renderChatReply('greeting')! : accessDenied);
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
      if (Date.now() >= this.nextSpamCleanup && await this.store.pruneSpamEvidence() < 2000) {
        this.nextSpamCleanup = Date.now() + 60_000;
      }
      await this.processDeadlines();
      for (const { outcome, finalizer_attempt, prompt_message_id } of await this.requests.finalizations()) {
        if (this.finalizing.has(outcome.request_id)) continue;
        this.finalizing.add(outcome.request_id);
        void this.finalize(outcome, finalizer_attempt, prompt_message_id);
      }
      const blockedChats = new Set<string>();
      const pendingChats = new Set<string>();
      for (const update of await this.store.pending()) {
        const earlierPending = pendingChats.has(update.chat_id);
        pendingChats.add(update.chat_id);
        if (this.processing.has(update.sequence) || this.replies.has(update.chat_id) || blockedChats.has(update.chat_id)) continue;
        if (earlierPending && update.payload.supportAction) {
          blockedChats.add(update.chat_id);
          continue;
        }
        const loadsAttachment = !!update.payload.attachment && update.submission_id === null;
        if (loadsAttachment && this.attachmentAdmissions >= 4) {
          blockedChats.add(update.chat_id);
          continue;
        }
        this.processing.add(update.sequence);
        try {
          await this.store.startProcessing(update.sequence);
          const admission = this.runReply(update.chat_id, () => this.admit(update));
          if (loadsAttachment) {
            this.attachmentAdmissions++;
            void admission.catch((error: unknown) => {
              this.processing.delete(update.sequence);
              blockedChats.add(update.chat_id);
              this.logFailure(update, error);
            }).finally(() => { this.attachmentAdmissions--; });
          } else {
            await admission;
          }
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
    if (update.spam_ban_expires_at || update.spam_ban_requested_at) {
      this.run(update, () => this.runReply(update.chat_id, async () => {
        if (update.spam_ban_expires_at) await this.notifySpamBan(update, update.spam_ban_expires_at);
        else if (update.spam_ban_requested_at && Date.now() - update.spam_ban_requested_at.getTime() < 60_000) {
          await this.applySpamBan(update);
        }
      }));
      return;
    }
    if (await this.store.wasSpamBlocked(update)) {
      this.sendService(update, 'banned');
      return;
    }
    let employee: boolean;
    let answer: string | null;
    try {
      employee = await isEmployee(update.payload);
      answer = update.command_answer ?? (update.instance_id === null && !update.payload.attachment
        ? await this.handle(update, employee) : null);
    } catch (error) {
      if (!(error instanceof UserBannedError)) throw error;
      this.sendService(update, 'banned');
      return;
    }
    const response = answer ?? (!employee ? accessDenied : null);
    if (response !== null) {
      this.run(update, async () => {
        if (response) {
          await this.output.send(`command:${update.update_id}`, update.chat_id, response, 'service', false);
        }
      });
      return;
    }
    if (update.spam_fingerprint && await this.store.evaluateSpam(update)) {
      this.run(update, () => this.runReply(update.chat_id, () => this.applySpamBan(update)));
      return;
    }

    const { attachment, text } = update.payload;
    let message: DeliveredMessageInput = text;
    if (attachment && update.submission_id === null) {
      const loaded = await loadAttachment(this.telegram, attachment, text);
      if ('error' in loaded) {
        this.sendService(update, 'attachment', loaded.error);
        return;
      }
      message = loaded.message;
    }

    const legacy = update.instance_id !== null && update.request_id === null;
    const request = legacy ? undefined : await this.acceptForRequest(update);
    if (!legacy && !request) return;
    const id = request?.instance_id ?? update.instance_id;
    if (!id) throw new Error('Missing Telegram request instance');
    const agent = init(Bars, { id });
    let submission = update.submission_id;
    if (submission === null) {
      if (!attachment && !update.payload.supportAction) {
        message = {
          kind: 'signal', type: telegramTextDelivery, tagName: 'telegram_message', body: text,
          attributes: {
            update_id: update.update_id,
            ...(request && !request.conversation_only ? { request_phase: request.phase } : {}),
          },
        };
      }
      const receipt = await agent.dispatch({
        message,
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
      let rich = true;
      let followUp: string | undefined;
      let buttons: SupportButtons | undefined;
      let action: SupportAction | undefined;
      let skip = false;
      let conversational = false;
      let reported = false;
      let available = true;
      let flags: ReplyFlags = { hasAnswer: false, hasClarification: false };
      try {
        const reply = await agent.read(submissionId);
        const savedAction = reply.data.supportAction?.at(-1);
        const parsedAction = v.safeParse(supportAction, savedAction);
        if (parsedAction.success) action = parsedAction.output;
        reported = reply.data.spamReport?.includes(update.update_id) ?? false;
        const responseId = reply.metadata?.telegramResponseId;
        if (typeof responseId === 'string') deliveryId = `response:${responseId}`;
        const ragResults = reply.data.ragAnswer;
        const parsedAttachment = v.safeParse(attachmentReply, reply.data.attachmentAnswer?.at(-1));
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
          flags = { hasAnswer: rendered.hasAnswer, hasClarification: rendered.hasClarification };
        } else if (parsedAttachment.success) {
          replyText = parsedAttachment.output.text;
          phase = parsedAttachment.output.kind === 'clarify' ? 'clarification' : 'answer';
          flags = {
            hasAnswer: parsedAttachment.output.kind === 'answer',
            hasClarification: parsedAttachment.output.kind === 'clarify',
          };
          rich = false;
        } else {
          const chat = v.safeParse(chatReply, reply.data.chatAnswer?.at(-1));
          if (chat.success) {
            skip = chat.output.kind === 'skip';
            if (chat.output.kind === 'reply') {
              replyText = chat.output.text;
              conversational = true;
              rich = false;
            }
          } else {
            replyText = renderChatReply(...(reply.data.chatAnswer ?? [])) ?? '';
            skip = !replyText && v.is(v.object({ action: v.literal('ban') }), savedAction);
          }
        }
      } catch (error) {
        if (!(error instanceof AgentRunError)) throw error;
        this.logFailure(update, error);
      } finally {
        stopTyping();
      }
      await this.runReply(update.chat_id, async () => {
        if (await this.store.wasSpamBlocked(update)) return;
        if (reported && await this.store.evaluateSpam(update, true)) {
          await this.applySpamBan(update);
          return;
        }
        if (skip && !action) return;
        if (!action && await responseSubmission(submissionId) !== submissionId) return;
        if (!replyText && !action) deliveryId = 'failure:' + submissionId;
        const kind = conversational ? 'service' : replyText && available ? 'answer' : 'fallback';
        if (!request) {
          const receipt = await this.output.send(
            deliveryId, update.chat_id, replyText || unavailable, kind, rich && !!replyText,
            { html: replyHtml, images: replyImages },
          );
          if (kind === 'answer') await this.recordReplyTiming(submissionId, receipt);
          return;
        }
        const active = await this.requests.active(update.chat_id);
        if (active?.id !== request.id || BigInt(active.phase_sequence) > BigInt(update.sequence)) return;
        if (action) {
          await this.applyAction(update, active, action);
          return;
        }
        if (conversational) {
          await this.deliver(request, deliveryId, replyText);
          return;
        }
        await this.dismissPrompt(active);
        await this.requests.clearDeadline(active, update.sequence);
        const receipt = await this.deliver(request, deliveryId, replyText || unavailable, {
          sequence: update.sequence, phase: followUp ? undefined : phase,
          html: replyHtml, rich: rich && !!replyText, kind, images: replyImages, buttons: followUp ? undefined : buttons, flags,
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

  private async applySpamBan(update: PendingUpdate): Promise<void> {
    const expiresAt = await banUser(update.payload.userId);
    await this.store.recordSpamBan(update, expiresAt);
    await this.notifySpamBan(update, expiresAt);
  }

  private async notifySpamBan(update: PendingUpdate, expiresAt: Date): Promise<void> {
    const seconds = Math.ceil((expiresAt.getTime() - Date.now()) / 1000);
    if (seconds > 0) {
      await this.output.send(`ban:${update.chat_id}:${expiresAt.getTime()}`, update.chat_id, bannedMessage(seconds), 'service', false);
    }
  }

  private async applyAction(update: PendingUpdate, request: ActiveRequest, action: SupportAction): Promise<void> {
    if (request.latest_sequence !== update.sequence || request.conversation_only) return;
    if (action.action === 'offer_close') {
      if (request.phase !== 'close_confirmation') {
        await this.dismissPrompt(request);
        await this.deliver(request, `offer-close:${update.update_id}`, closeQuestion, {
          sequence: update.sequence, phase: 'close_confirmation', buttons: 'close', optional: true,
          flags: { hasAnswer: false, hasClarification: false },
        });
      }
      return;
    }
    if (await this.requests.close(request, update.sequence, action.reason)) {
      await this.output.send(`closed:${update.update_id}`, update.chat_id, closedAnswer, 'service', false);
    }
  }

  private async dismissPrompt(request: Pick<ActiveRequest, 'id' | 'chat_id' | 'prompt_message_id'>): Promise<void> {
    if (request.prompt_message_id === null) return;
    await this.output.removeKeyboard(request.chat_id, request.prompt_message_id);
    await this.requests.clearPrompt(request.id, request.prompt_message_id);
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
    const { attachment, text: message } = update.payload;
    const text = attachment ? '' : shortReply(message);
    const close = isCloseRequest(text);
    const action = update.payload.supportAction;
    const current = await this.requests.active(update.chat_id);
    if (update.request_id && current?.id !== update.request_id) {
      const reason = await this.requests.closedBy(update);
      this.sendService(update, 'closed', closeAcknowledgement(reason), action?.messageId);
      return;
    }
    const previous = update.request_phase ?? current?.phase;
    if (action && (current?.id !== action.requestId
      || (current.phase_sequence !== action.sequence && current.phase_sequence !== update.sequence)
      || (action.kind === 's'
        ? previous !== 'details' && previous !== 'handoff_confirmation'
        : action.kind === 'n' ? previous !== 'feedback'
          : action.kind === 'c' ? previous !== 'close_confirmation'
            : previous !== 'feedback' && previous !== 'close_confirmation'))) {
      const messageId = action.messageId;
      this.run(update, () => this.runReply(update.chat_id, async () => {
        if (messageId !== undefined && current?.prompt_message_id !== messageId) {
          await this.output.removeKeyboard(update.chat_id, messageId);
        }
      }));
      return;
    }
    if ((!current || current.conversation_only) && close) {
      this.sendService(update, 'chat', 'У вас нет открытого обращения.');
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
    const yes = (markingSolved || confirmingClose) && /^(?:да|(?:да,? )?закрыть)$/u.test(text);
    const no = markingSolved && /^(?:нет|нет,? нужна помощь)$/u.test(text);
    const keepOpen = confirmingClose && /^(?:нет|нет,? продолжим|продолжить|продолжим)$/u.test(text);
    const historyText = attachment ? [message, `[${attachmentSummary(attachment)}]`].filter(Boolean).join('\n')
      : close || yes || no || keepOpen || handoff || declinedHandoff || action ? message : null;
    await this.requests.append(request, `user:${update.update_id}`, 'user', update.received_at, historyText, update.sequence);
    const reason = close || (yes && confirmingClose) ? 'user_closed'
      : handoff ? 'operator_requested' : yes ? 'confirmed' : undefined;
    if (reason) {
      const draft = reason === 'operator_requested' ? {
        title: 'Требуется помощь специалиста',
        description: 'Сотрудник попросил передать обращение специалисту. Детали есть в переписке.',
      } : undefined;
      const closed = await this.requests.close(request, update.sequence, reason, draft);
      this.sendService(update, 'closed', closed ? closeAcknowledgement(reason) : undefined, action?.messageId);
      return;
    }
    if (no || keepOpen || declinedHandoff) {
      if (request.prompt_message_id !== action?.messageId) await this.dismissPrompt(request);
      await this.requests.clearDeadline(request, update.sequence);
      const prompt = declinedHandoff
        ? 'Хорошо. Если появятся новые детали, напишите.'
        : keepOpen ? 'Хорошо, продолжим. Что ещё уточнить?' : detailsQuestion;
      this.run(update, () => this.runReply(update.chat_id, async () => {
        await this.deliver(request, `prompt:${update.update_id}`, prompt, {
          sequence: update.sequence, phase: declinedHandoff ? 'clarification' : 'details', replaceMessageId: action?.messageId,
        });
      }));
      return;
    }
    return request;
  }

  private sendService(update: PendingUpdate, prefix: string, text?: string, replaceMessageId?: number): void {
    this.run(update, () => this.runReply(update.chat_id, async () => {
      if (text) {
        await this.output.send(
          `${prefix}:${update.update_id}`, update.chat_id, text, 'service', false, { replaceMessageId },
        );
      }
    }));
  }

  private async deliver(
    request: ActiveRequest, id: string, text: string,
    next?: {
      sequence?: string; phase?: RequestPhase; rich?: boolean; html?: string;
      kind?: DeliveryKind; images?: string[]; buttons?: SupportButtons; optional?: boolean; flags?: ReplyFlags;
      replaceMessageId?: number;
    },
  ): Promise<DeliveryResult> {
    const keyboard = next?.buttons && next.sequence
      ? getSupportKeyboard(next.buttons, request.id, next.sequence) : undefined;
    const receipt = await this.output.send(
      id, request.chat_id, text, next?.kind ?? 'service', next?.rich ?? false,
      { html: next?.html, images: next?.images, keyboard, replaceMessageId: next?.replaceMessageId },
    );
    if (receipt.status !== 'sent' || !receipt.sent_at) {
      if (next?.sequence && !next.optional) await this.requests.close(request, next.sequence, 'delivery_failed');
      return receipt;
    }
    const flags = next?.flags ?? {
      hasAnswer: false,
      hasClarification: next?.phase === 'clarification' || next?.phase === 'details'
        || next?.phase === 'handoff_confirmation' || next?.phase === 'close_confirmation',
    };
    await this.requests.append(request, id, 'assistant', receipt.sent_at, text, undefined, flags);
    if (next?.sequence && next.phase) {
      await this.requests.advance(request, next.sequence, next.phase, receipt.sent_at, receipt.message_id);
    }
    return receipt;
  }

  private async processDeadlines(): Promise<void> {
    for (const request of await this.requests.due()) {
      if (this.replies.has(request.chat_id)) continue;
      void this.runReply(request.chat_id, async () => {
        const [due] = await this.requests.due(request.id);
        if (!due) return;
        if (due.conversation_only) {
          await this.requests.expireConversation(due);
        } else {
          await this.requests.close(due, due.latest_sequence, timeoutReasons[due.phase], undefined, true);
        }
      }).catch((error: unknown) => {
        console.warn('Telegram request deadline failed', request.id, error instanceof Error ? error.name : 'Error');
      });
    }
  }

  private async finalize(outcome: ClosedRequest, attempt: number, promptMessageId: number | null): Promise<void> {
    const id = outcome.request_id;
    try {
      if (promptMessageId !== null) {
        await this.runReply(outcome.telegram_chat_id, () => this.dismissPrompt({
          id, chat_id: outcome.telegram_chat_id, prompt_message_id: promptMessageId,
        }));
      }
      if (outcome.handoff) {
        const finalizer = init(SupportRequestFinalizer, { id });
        const receipt = await finalizer.dispatch({
          message: { kind: 'signal', type: supportRequestClosed, body: JSON.stringify(outcome) },
          idempotencyKey: `support-request:${id}:${attempt}`,
        });
        await finalizer.read(receipt);
        const url = await getSupportTicketUrl(id);
        const chatId = outcome.telegram_chat_id;
        await this.runReply(chatId, async () => {
          await this.output.send(`ticket-created:${id}`, chatId, `Заявка создана в Jira.\n${url}`, 'service', false);
        });
      } else {
        await saveSupportRequestOutcome(outcome);
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
