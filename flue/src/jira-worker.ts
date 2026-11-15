import * as v from 'valibot';

import { botRequest } from './bot-api.js';
import type { JiraStore, PendingJiraComment } from './jira-store.js';
import { TelegramOutput } from './telegram-output.js';

const recipient = v.object({
  telegram_chat_id: v.pipe(v.string(), v.regex(/^[1-9][0-9]{0,18}$/)),
});

export class JiraWorker {
  private scanning = false;

  constructor(private readonly store: JiraStore, private readonly output: TelegramOutput) {}

  async scan(): Promise<void> {
    if (this.scanning) return;
    this.scanning = true;
    try {
      for (let count = 0; count < 20; count++) {
        const event = await this.store.claim();
        if (!event) break;
        try {
          await this.deliver(event);
        } catch (error) {
          console.warn('Jira comment processing failed', event.issue_id, event.comment_id,
            error instanceof Error ? error.name : 'Error');
          await this.store.retry(event);
        }
      }
    } catch (error) {
      console.warn('Jira queue scan failed', error instanceof Error ? error.name : 'Error');
    } finally {
      this.scanning = false;
    }
  }

  private async deliver(event: PendingJiraComment): Promise<void> {
    const comment = event.payload;
    const query = new URLSearchParams({ issue_id: comment.issue_id });
    const response = await botRequest(`tickets/by-external-key/${encodeURIComponent(comment.issue_key)}/recipient?${query}`);
    if (response.status === 404) {
      await response.body?.cancel();
      if (event.attempts < 10) {
        await this.store.retry(event);
      } else {
        await this.store.finish(event, 'ignored');
        console.warn('Jira comment has no linked Telegram recipient', comment.issue_key, comment.comment_id);
      }
      return;
    }
    if (!response.ok) {
      await response.body?.cancel();
      throw new Error(`Jira recipient API status ${response.status}`);
    }
    const { telegram_chat_id } = v.parse(recipient, await response.json());
    const author = comment.author.trim() ? ` (${comment.author})` : '';
    const text = `Ответ поддержки по заявке ${comment.issue_key}${author}:\n\n${comment.comment}`;
    const delivery = await this.output.send(
      `jira:${comment.issue_id}:${comment.comment_id}`, telegram_chat_id, text, 'service', false,
    );
    if (delivery.status === 'sending') {
      await this.store.retry(event);
      return;
    }
    await this.store.finish(event, delivery.status);
    console.log('Jira comment delivery', comment.issue_key, comment.comment_id, delivery.status);
  }
}
