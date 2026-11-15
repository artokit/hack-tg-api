import * as v from 'valibot';

import { botRequest } from './bot-api.js';

const remainingBan = v.object({
  retry_after_seconds: v.pipe(v.number(), v.integer(), v.minValue(1), v.maxValue(600)),
});
const createdBan = v.object({
  expires_at_ms: v.pipe(v.number(), v.safeInteger(), v.minValue(1), v.maxValue(8_640_000_000_000_000)),
});
const minutePlural = new Intl.PluralRules('ru-RU');
const minuteForms: Record<string, string> = { one: 'минуту', few: 'минуты', many: 'минут', other: 'минут' };

export class UserBannedError extends Error {
  constructor(readonly retryAfterSeconds: number) {
    super('User is banned');
    this.name = 'UserBannedError';
  }
}

export async function banRemaining(response: Response): Promise<number> {
  return v.parse(remainingBan, await response.json()).retry_after_seconds;
}

export async function banUser(telegramId: number): Promise<Date> {
  const response = await botRequest('bans', {
    method: 'POST', body: JSON.stringify({ telegram_id: telegramId }),
  });
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(`Bans API status ${response.status}`);
  }
  return new Date(v.parse(createdBan, await response.json()).expires_at_ms);
}

export function bannedMessage(seconds: number): string {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return `Вы временно заблокированы за флуд или спам. Сейчас писать боту нельзя. Попробуйте снова через ${minutes} ${minuteForms[minutePlural.select(minutes)]}.`;
}
