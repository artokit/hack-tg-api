import { httpUrl, required } from './config.js';

export function botRequest(path: string, options?: RequestInit): Promise<Response> {
  return apiRequest(`/private/${path}`, options);
}

export function apiRequest(path: string, options?: RequestInit): Promise<Response> {
  const headers = new Headers(options?.headers);
  headers.set('X-Bot-Token', required('BOT_API_TOKEN'));
  if (typeof options?.body === 'string') headers.set('Content-Type', 'application/json');
  return fetch(`${httpUrl('API_URL')}${path}`, {
    ...options,
    headers,
    signal: options?.signal ?? AbortSignal.timeout(5_000),
  });
}
