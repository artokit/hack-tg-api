import { httpUrl } from './config.js';
import type { IncomingMessage } from './telegram-store.js';

const unavailable = 'Сейчас не получается принять приглашение. Попробуй чуть позже.';

export async function acceptInvite(id: string, message: IncomingMessage): Promise<string> {
  const token = process.env.BOT_API_TOKEN?.trim();
  if (!token) return unavailable;
  try {
    const response = await fetch(`${httpUrl('API_URL')}/private/invites/${id}/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Bot-Token': token },
      body: JSON.stringify({
        telegram_id: message.userId,
        username: message.username ?? null,
        first_name: message.firstName,
        last_name: message.lastName ?? null,
      }),
      signal: AbortSignal.timeout(5_000),
    });
    if (response.status === 404) return 'Приглашение больше не действует или уже использовано.';
    if (response.status === 409) return 'Ты уже зарегистрирован как сотрудник.';
    if (response.status !== 201) return unavailable;
    return 'Приглашение принято! Ты присоединился как сотрудник. Можешь написать свой вопрос.';
  } catch {
    return unavailable;
  }
}
