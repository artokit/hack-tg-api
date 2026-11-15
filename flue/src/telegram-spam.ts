import { createHash } from 'node:crypto';

export const telegramTextDelivery = 'telegram_text';

export function spamFingerprint(text: string): string {
  const normalized = text.toLowerCase().trim().replace(/\s+/gu, ' ');
  return createHash('sha256').update(normalized).digest('hex');
}
