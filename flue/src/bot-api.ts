import { httpUrl, required } from './config.js';

export function botRequest(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`${httpUrl('API_URL')}/private/${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Bot-Token': required('BOT_API_TOKEN') },
    signal: AbortSignal.timeout(5_000),
  });
}
