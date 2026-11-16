import { InlineKeyboard } from 'grammy';

export interface SupportAction {
  kind: 'y' | 'n' | 's' | 'c';
  requestId: string;
  sequence: string;
}

export type SupportButtons = 'close' | 'operator';

export const supportActionText = {
  y: 'Да, закрыть',
  n: 'Нет, нужна помощь',
  s: 'Связаться с поддержкой',
  c: 'Нет, продолжим',
} as const;

const buttonLabels = {
  close: { y: 'Закрыть', c: 'Продолжить' },
  operator: { s: supportActionText.s },
} as const;

export function parseSupportAction(data?: string): SupportAction | undefined {
  const match = /^bars:([ynsc]):([\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}):(\d{1,19})$/u.exec(data ?? '');
  if (!match) return;
  const [, kind, requestId, sequence] = match;
  if (kind === 'y' || kind === 'n' || kind === 's' || kind === 'c') return { kind, requestId, sequence };
}

export function getSupportKeyboard(buttons: SupportButtons, requestId: string, sequence: string): InlineKeyboard {
  const keyboard = new InlineKeyboard();
  for (const [action, label] of Object.entries(buttonLabels[buttons])) {
    keyboard.text(label, `bars:${action}:${requestId}:${sequence}`);
  }
  return keyboard;
}
