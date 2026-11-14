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

function telegramProfile(message: IncomingMessage) {
  return {
    username: message.username ?? null,
    first_name: message.firstName ?? null,
    last_name: message.lastName ?? null,
  };
}

export async function isEmployee(message: IncomingMessage): Promise<boolean> {
  const path = `employees/by-telegram-id/${message.userId}`;
  const response = await botRequest(path);
  if (response.status === 404) return false;
  if (!response.ok) throw new Error(`Employees API status ${response.status}`);
  const employee = await response.json() as { is_parsed: boolean };
  if (employee.is_parsed !== true) {
    const updated = await botRequest(path, {
      method: 'PATCH',
      body: JSON.stringify(telegramProfile(message)),
    });
    if (updated.status === 404) return false;
    if (!updated.ok) throw new Error(`Employees API status ${updated.status}`);
  }
  return true;
}

export async function acceptInvite(id: string, message: IncomingMessage): Promise<boolean> {
  const response = await botRequest(`invites/${id}/accept`, {
    method: 'POST',
    body: JSON.stringify({
      telegram_id: message.userId,
      ...telegramProfile(message),
    }),
  });
  if (response.status >= 500 || response.status === 429) {
    throw new Error(`Invites API status ${response.status}`);
  }
  return response.status === 201;
}
