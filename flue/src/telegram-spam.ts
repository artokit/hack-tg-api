import { createHash } from 'node:crypto';

export const telegramTextDelivery = 'telegram_text';

export function spamFingerprint(text: string): string {
  const normalized = text.toLowerCase().trim().replace(/\s+/gu, ' ');
  const exact = createHash('sha256').update(normalized).digest('hex');
  const repeatedLetter = /^(\p{L})\1{3,}$/u.exec(normalized.replaceAll(' ', ''))?.[1];
  if (!repeatedLetter) return exact;
  const repeated = createHash('sha256').update(repeatedLetter).digest('hex');
  return `${exact}:${repeated}`;
}
