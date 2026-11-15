import { setTimeout as delay } from 'node:timers/promises';
import { Api, GrammyError, HttpError, type InlineKeyboard, InputFile } from 'grammy';

import { fetchRagImage } from './rag-visual.js';
import { recordDelivery } from './telemetry.js';
import type { DeliveryKind, DeliveryReceipt, DeliveryStatus, TelegramStore } from './telegram-store.js';

export type DeliveryResult = DeliveryReceipt & { startedAt?: number; finishedAt?: number };
type ReplyPhoto = { id: string; media: { type: 'photo'; media: InputFile } };
const emptyKeyboard = { inline_keyboard: [] };

export function splitReply(text: string): string[] {
  const parts: string[] = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + 4096, text.length);
    const last = text.charCodeAt(end - 1);
    if (end < text.length && last >= 0xd800 && last <= 0xdbff) end--;
    parts.push(text.slice(start, end));
    start = end;
  }
  return parts;
}

async function withRateLimit<T>(send: () => Promise<T>): Promise<T> {
  try {
    return await send();
  } catch (error) {
    if (!(error instanceof GrammyError) || error.error_code !== 429) throw error;
    const seconds = error.parameters.retry_after;
    if (seconds === undefined) throw error;
    await delay(seconds * 1000);
    return await send();
  }
}

async function editWithRetry<T>(edit: () => Promise<T>): Promise<T> {
  try {
    return await withRateLimit(edit);
  } catch (error) {
    if (!(error instanceof HttpError || (error instanceof GrammyError && error.error_code >= 500))) throw error;
    await delay(250);
    return withRateLimit(edit);
  }
}

async function loadReplyPhotos(images: string[]): Promise<ReplyPhoto[]> {
  const files = await Promise.all(images.map((id) => fetchRagImage(id, undefined, true)));
  return files.flatMap((file, index) => file ? [{
    id: `photo_${index + 1}`,
    media: { type: 'photo', media: new InputFile(file, `screenshot-${index + 1}.png`) },
  }] : []);
}

export class TelegramOutput {
  private readonly typing = new Map<string, { count: number; controller: AbortController }>();

  constructor(private readonly client: Api, private readonly store: TelegramStore) {}

  beginTyping(chatId: string): () => void {
    let active = this.typing.get(chatId);
    if (!active) {
      active = { count: 0, controller: new AbortController() };
      this.typing.set(chatId, active);
      void this.keepTyping(chatId, active.controller.signal);
    }

    active.count++;
    const current = active;
    return () => {
      current.count--;
      if (current.count === 0) {
        current.controller.abort();
        this.typing.delete(chatId);
      }
    };
  }

  private async keepTyping(chatId: string, signal: AbortSignal): Promise<void> {
    while (!signal.aborted) {
      let wait = 4_000;
      try {
        await this.client.sendChatAction(
          chatId, 'typing',
        );
      } catch (error) {
        if (error instanceof GrammyError && error.error_code === 429) {
          wait = (error.parameters.retry_after ?? 4) * 1000;
        }
      }
      await delay(wait, undefined, { signal }).catch(() => {});
    }
  }

  async send(
    id: string, chatId: string, text: string, kind: DeliveryKind, markdown: boolean,
    { html, images, keyboard, replaceMessageId }: {
      html?: string; images?: string[]; keyboard?: InlineKeyboard; replaceMessageId?: number;
    } = {},
  ): Promise<DeliveryResult> {
    const media = html && images?.length ? await loadReplyPhotos(images) : [];
    if (!await this.store.claimDelivery(id, kind)) return this.store.delivery(id);
    const startedAt = Date.now();
    let status: DeliveryStatus = 'sent';
    let messageId: number | null = null;
    try {
      messageId = replaceMessageId !== undefined && await this.replaceMessage(chatId, replaceMessageId, text, keyboard)
        ? replaceMessageId : await this.sendMessage(chatId, text, markdown, html, media, keyboard);
    } catch (error) {
      status = error instanceof GrammyError && error.error_code < 500 ? 'failed' : 'unknown';
      console.warn('Telegram delivery', status, id, error instanceof Error ? error.name : 'Error');
    }
    const finishedAt = Date.now();
    const receipt = await this.store.recordDelivery(id, status, keyboard ? messageId : null);
    recordDelivery(kind, status);
    return { ...receipt, startedAt, finishedAt };
  }

  async removeKeyboard(chatId: string, messageId: number): Promise<void> {
    try {
      await editWithRetry(() => this.client.editMessageReplyMarkup(chatId, messageId, { reply_markup: emptyKeyboard }));
    } catch (error) {
      if (!(error instanceof GrammyError) || ![400, 403].includes(error.error_code)) throw error;
      if (!error.description.includes('message is not modified')) {
        console.warn('Telegram keyboard removal rejected', messageId, error.error_code);
      }
    }
  }

  private async replaceMessage(chatId: string, messageId: number, text: string, keyboard?: InlineKeyboard): Promise<boolean> {
    try {
      await editWithRetry(() => this.client.editMessageText(
        chatId, messageId, text, { reply_markup: keyboard ?? emptyKeyboard },
      ));
      return true;
    } catch (error) {
      if (!(error instanceof GrammyError) || ![400, 403].includes(error.error_code)) throw error;
      if (error.error_code === 400 && error.description.includes('message is not modified')) return true;
    }
    await this.removeKeyboard(chatId, messageId);
    return false;
  }

  private async sendMessage(
    chatId: string, text: string, markdown: boolean, html: string | undefined, media: ReplyPhoto[],
    keyboard?: InlineKeyboard,
  ): Promise<number | null> {
    const options = keyboard && { reply_markup: keyboard };
    if (html && media.length) {
      const photos = media.map(({ id }) => `<img src="tg://photo?id=${id}"/>`).join('');
      try {
        const sent = await withRateLimit(() => this.client.sendRichMessage(chatId, { html: html + photos, media }, options));
        return sent.message_id;
      } catch (error) {
        if (!(error instanceof GrammyError) || ![400, 413].includes(error.error_code)) throw error;
      }
    }
    if (html || markdown) {
      try {
        const sent = await withRateLimit(() => this.client.sendRichMessage(chatId, html ? { html } : { markdown: text }, options));
        return sent.message_id;
      } catch (error) {
        if (!(error instanceof GrammyError) || error.error_code !== 400) throw error;
      }
    }
    const parts = splitReply(text);
    let messageId: number | null = null;
    for (const [index, part] of parts.entries()) {
      const sent = await withRateLimit(() => this.client.sendMessage(chatId, part, index === parts.length - 1 ? options : undefined));
      messageId = sent.message_id;
    }
    return messageId;
  }
}
