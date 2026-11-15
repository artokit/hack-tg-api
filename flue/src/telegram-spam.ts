import { createHash } from 'node:crypto';

export const telegramTextDelivery = 'telegram_text';

interface SpamRule {
  minMessages: number;
  windowSeconds: number;
  minReports: number;
}

function positiveInteger(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number(raw);
  if (!/^\d+$/u.test(raw) || value < 1 || value > 2_147_483_647) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

function rule(name: string, defaults: SpamRule): SpamRule {
  const prefix = `TELEGRAM_SPAM_${name}`;
  const minMessages = positiveInteger(`${prefix}_MIN_MESSAGES`, defaults.minMessages);
  const windowSeconds = positiveInteger(`${prefix}_WINDOW_SECONDS`, defaults.windowSeconds);
  const minReports = positiveInteger(`${prefix}_MIN_REPORTS`, defaults.minReports);
  if (minReports > minMessages) throw new Error(`${prefix}_MIN_REPORTS must not exceed ${prefix}_MIN_MESSAGES`);
  return { minMessages, windowSeconds, minReports };
}

const exactCopies = rule('EXACT_COPY', { minMessages: 5, windowSeconds: 60, minReports: 2 });
const burst = rule('BURST', { minMessages: 5, windowSeconds: 10, minReports: 1 });

export const telegramSpamPolicy = {
  exactCopies,
  burst,
  evidenceSeconds: Math.max(exactCopies.windowSeconds, burst.windowSeconds),
};

export function spamFingerprint(text: string): string {
  const normalized = text.toLowerCase().trim().replace(/\s+/gu, ' ');
  return createHash('sha256').update(normalized).digest('hex');
}
