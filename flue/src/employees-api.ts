import { httpUrl, required } from './config.js';
import type { IncomingMessage } from './telegram-store.js';

export const accessDenied = 'Доступ к боту только для сотрудников. Попроси действующее приглашение.';
export const accessGranted = 'Тебя добавили в бота. Теперь можешь задавать вопросы.';

function botRequest(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`${httpUrl('API_URL')}/private/${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Bot-Token': required('BOT_API_TOKEN') },
    signal: AbortSignal.timeout(5_000),
  });
}

export async function isEmployee(telegramId: number): Promise<boolean> {
  const response = await botRequest(`employees/by-telegram-id/${telegramId}`);
  if (response.status === 404) return false;
  if (!response.ok) throw new Error(`Employees API status ${response.status}`);
  return true;
}

export async function acceptInvite(id: string, message: IncomingMessage, name: string): Promise<boolean> {
  const response = await botRequest(`invites/${id}/accept`, {
    method: 'POST',
    body: JSON.stringify({
      telegram_id: message.userId,
      username: message.username ?? null,
      first_name: name,
      last_name: null,
    }),
  });
  if (response.status >= 500 || response.status === 429) {
    throw new Error(`Invites API status ${response.status}`);
  }
  return response.status === 201;
}
