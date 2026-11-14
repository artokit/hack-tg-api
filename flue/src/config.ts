export function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

export function httpUrl(name: string): string {
  const url = new URL(required(name));
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(`${name} must be an HTTP URL`);
  }
  return url.href.replace(/\/$/, '');
}

export function webhookSecret(): string {
  const secret = required('TELEGRAM_WEBHOOK_SECRET_TOKEN');
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(secret)) {
    throw new Error('Invalid TELEGRAM_WEBHOOK_SECRET_TOKEN');
  }
  return secret;
}
