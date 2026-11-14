import { setTimeout as delay } from 'node:timers/promises';
import { Api, GrammyError } from 'grammy';

import type { TelegramStore } from './telegram-store.js';

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

  async send(id: string, chatId: string, text: string, markdown: boolean): Promise<void> {
    if (!await this.store.claimDelivery(id)) return;
    let status: 'sent' | 'failed' | 'unknown';
    try {
      if (markdown) {
        try {
          await withRateLimit(() => this.client.sendRichMessage(chatId, { markdown: text }));
          await this.store.recordDelivery(id, 'sent');
          return;
        } catch (error) {
          if (!(error instanceof GrammyError) || error.error_code !== 400) throw error;
        }
      }
      for (const part of splitReply(text)) {
        await withRateLimit(() => this.client.sendMessage(chatId, part));
      }
      status = 'sent';
    } catch (error) {
      status = error instanceof GrammyError && error.error_code < 500 ? 'failed' : 'unknown';
      console.warn('Telegram delivery', status, id, error instanceof Error ? error.name : 'Error');
    }
    await this.store.recordDelivery(id, status);
  }
}
