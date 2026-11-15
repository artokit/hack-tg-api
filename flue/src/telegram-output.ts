import { createHash } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { Api, GrammyError, HttpError, type InlineKeyboard, InputFile } from 'grammy';

import { fetchRagImage } from './rag-visual.js';
import { recordDelivery } from './telemetry.js';
import type { DeliveryKind, DeliveryReceipt, DeliveryStatus, TelegramStore } from './telegram-store.js';

export type DeliveryResult = DeliveryReceipt & { startedAt?: number; finishedAt?: number };
export type RichReplyBlock = { html: string; headingHtml?: string; images?: string[] };
type ReplyPhoto = { id: string; media: { type: 'photo'; media: InputFile } };

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

async function loadReplyPhotos(blocks: RichReplyBlock[]): Promise<Map<string, ReplyPhoto>> {
  const images = [...new Set(blocks.flatMap((block) => block.images ?? []))];
  const files = await Promise.all(images.map(async (id) => ({ id, file: await fetchRagImage(id, undefined, true) })));
  const hashes = new Set<string>();
  const photos = new Map<string, ReplyPhoto>();
  for (const { id, file } of files) {
    if (!file) continue;
    const hash = createHash('sha256').update(file).digest('hex');
    if (hashes.has(hash)) continue;
    hashes.add(hash);
    const number = photos.size + 1;
    photos.set(id, {
      id: `photo_${number}`,
      media: { type: 'photo', media: new InputFile(file, `screenshot-${number}.png`) },
    });
  }
  return photos;
}

function renderRichBlocks(blocks: RichReplyBlock[], photos?: Map<string, ReplyPhoto>): string {
  return blocks.map(({ html, headingHtml = '', images = [] }) => {
    const attachments = images.map((id) => {
      const photo = photos?.get(id);
      return photo ? `<img src="tg://photo?id=${photo.id}"/>` : '';
    }).join('');
    return html || attachments ? headingHtml + html + attachments : '';
  }).join('');
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
    { blocks = [], keyboard, replaceMessageId }: {
      blocks?: RichReplyBlock[]; keyboard?: InlineKeyboard; replaceMessageId?: number;
    } = {},
  ): Promise<DeliveryResult> {
    const photos = blocks.length ? await loadReplyPhotos(blocks) : new Map<string, ReplyPhoto>();
    if (!await this.store.claimDelivery(id, kind)) return this.store.delivery(id);
    const startedAt = Date.now();
    let status: DeliveryStatus = 'sent';
    try {
      if (replaceMessageId === undefined || !await this.replaceMessage(chatId, replaceMessageId, text, keyboard)) {
        await this.sendMessage(chatId, text, markdown, blocks, photos, keyboard);
      }
    } catch (error) {
      status = error instanceof GrammyError && error.error_code < 500 ? 'failed' : 'unknown';
      console.warn('Telegram delivery', status, id, error instanceof Error ? error.name : 'Error');
    }
    const finishedAt = Date.now();
    const receipt = await this.store.recordDelivery(id, status);
    recordDelivery(kind, status);
    return { ...receipt, startedAt, finishedAt };
  }

  private async replaceMessage(chatId: string, messageId: number, text: string, keyboard?: InlineKeyboard): Promise<boolean> {
    const emptyKeyboard = { inline_keyboard: [] };
    const edit = () => withRateLimit(() => this.client.editMessageText(
      chatId, messageId, text, { reply_markup: keyboard ?? emptyKeyboard },
    ));
    try {
      await edit().catch(async (error: unknown) => {
        if (!(error instanceof HttpError || (error instanceof GrammyError && error.error_code >= 500))) throw error;
        await delay(250);
        await edit();
      });
      return true;
    } catch (error) {
      if (!(error instanceof GrammyError) || ![400, 403].includes(error.error_code)) throw error;
      if (error.error_code === 400 && error.description.includes('message is not modified')) return true;
    }
    try {
      await withRateLimit(() => this.client.editMessageReplyMarkup(chatId, messageId, { reply_markup: emptyKeyboard }));
    } catch (error) {
      console.warn('Telegram keyboard removal failed', messageId, error instanceof Error ? error.name : 'Error');
    }
    return false;
  }

  private async sendMessage(
    chatId: string, text: string, markdown: boolean, blocks: RichReplyBlock[], photos: Map<string, ReplyPhoto>,
    keyboard?: InlineKeyboard,
  ): Promise<void> {
    const options = keyboard && { reply_markup: keyboard };
    if (photos.size) {
      const html = renderRichBlocks(blocks, photos);
      const media = [...photos.values()];
      try {
        await withRateLimit(() => this.client.sendRichMessage(chatId, { html, media }, options));
        return;
      } catch (error) {
        if (!(error instanceof GrammyError) || ![400, 413].includes(error.error_code)) throw error;
      }
    }
    const html = renderRichBlocks(blocks);
    if (html || markdown) {
      try {
        await withRateLimit(() => this.client.sendRichMessage(chatId, html ? { html } : { markdown: text }, options));
        return;
      } catch (error) {
        if (!(error instanceof GrammyError) || error.error_code !== 400) throw error;
      }
    }
    const parts = splitReply(text);
    for (const [index, part] of parts.entries()) {
      await withRateLimit(() => this.client.sendMessage(chatId, part, index === parts.length - 1 ? options : undefined));
    }
  }
}
