import type { DeliveredMessage } from '@flue/runtime';
import { type Api, GrammyError } from 'grammy';
import * as v from 'valibot';

import { botRequest } from './bot-api.js';
import { httpUrl } from './config.js';
import { contextWindow } from './provider.js';

const maxBytes = 10 * 1024 * 1024;
const documentMarker = '\n\n<telegram_attachment>\n';
const documentEnd = '\n</telegram_attachment>';
const tooLarge = 'Файл слишком большой. Пришлите файл размером до 10 МиБ.';
const unsupported = 'Этот формат не поддерживается. Пришлите фото, JPEG, PNG, PDF, DOCX, TXT или Markdown.';
const downloadFailed = 'Не удалось скачать файл из Telegram. Попробуйте отправить его ещё раз.';
const readFailed = 'Не удалось прочитать файл. Проверьте, что он открывается, или пришлите нужный фрагмент скриншотом.';
const documentText = v.object({ text: v.string(), truncated: v.boolean() });
const formats = new Map([
  ['image/jpeg', '.jpg'],
  ['image/png', '.png'],
  ['application/pdf', '.pdf'],
  ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx'],
  ['text/plain', '.txt'],
  ['text/markdown', '.md'],
]);

export type TelegramAttachment = {
  kind: 'photo' | 'document';
  fileId: string;
  filename?: string;
  mimeType?: string;
  size?: number;
};

type LoadedAttachment = { message: Extract<DeliveredMessage, { kind: 'user' }> } | { error: string };

export function attachmentSummary(attachment: TelegramAttachment): string {
  return attachment.kind === 'photo' ? 'Фото' : `Файл: ${attachment.filename ?? 'без имени'}`;
}

export function questionFromDelivery(body: string): string {
  const start = body.endsWith(documentEnd) ? body.lastIndexOf(documentMarker) : -1;
  return start < 0 ? body : body.slice(0, start);
}

async function download(telegram: Api, fileId: string): Promise<Buffer<ArrayBuffer> | { error: string }> {
  try {
    const file = await telegram.getFile(fileId);
    if ((file.file_size ?? 0) > maxBytes) return { error: tooLarge };
    const segments = file.file_path?.split('/');
    if (!segments?.length || segments.some((part) => !part || part === '.' || part === '..')) {
      return { error: downloadFailed };
    }
    const root = process.env.TELEGRAM_API_ROOT ? httpUrl('TELEGRAM_API_ROOT') : 'https://api.telegram.org';
    const url = `${root}/file/bot${telegram.token}/${segments.map(encodeURIComponent).join('/')}`;
    const response = await fetch(url, { signal: AbortSignal.timeout(12_000), redirect: 'error' });
    if (!response.ok || Number(response.headers.get('content-length')) > maxBytes) {
      await response.body?.cancel();
      return { error: response.ok ? tooLarge : downloadFailed };
    }
    if (!response.body) return { error: downloadFailed };
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        return { error: tooLarge };
      }
      chunks.push(value);
    }
    return Buffer.concat(chunks, size);
  } catch (error) {
    const large = error instanceof GrammyError && error.error_code === 400 && /file is too big/i.test(error.description);
    return { error: large ? tooLarge : downloadFailed };
  }
}

export async function loadAttachment(telegram: Api, attachment: TelegramAttachment, caption: string): Promise<LoadedAttachment> {
  if ((attachment.size ?? 0) > maxBytes) return { error: tooLarge };
  const extension = attachment.kind === 'photo' ? '.jpg'
    : attachment.filename?.match(/\.[^.]+$/)?.[0].toLowerCase() ?? formats.get(attachment.mimeType ?? '') ?? '';
  const image = extension === '.jpg' || extension === '.jpeg' || extension === '.png';
  const pdf = extension === '.pdf';
  if (!image && !pdf && !['.docx', '.txt', '.md', '.markdown'].includes(extension)) {
    return { error: unsupported };
  }
  const data = await download(telegram, attachment.fileId);
  if (!Buffer.isBuffer(data)) return data;
  const body = caption || `Пользователь отправил вложение без подписи. ${attachmentSummary(attachment)}.`;
  if (image) {
    const mimeType = data.subarray(0, 8).toString('hex') === '89504e470d0a1a0a' ? 'image/png'
      : data.subarray(0, 3).toString('hex') === 'ffd8ff' ? 'image/jpeg' : undefined;
    if (!mimeType) return { error: readFailed };
    return { message: {
      kind: 'user', body,
      attachments: [{ type: 'image', data: data.toString('base64'), mimeType, filename: attachment.filename }],
    } };
  }
  try {
    const response = await botRequest(`telegram/attachment-text?format=${extension.slice(1)}`, {
      method: 'POST', body: data, signal: AbortSignal.timeout(12_000),
    });
    if (response.status === 413) return { error: tooLarge };
    if (response.status === 415) return { error: unsupported };
    if (response.status === 422) {
      const detail = await response.json() as { detail?: string };
      if (pdf && detail.detail === 'empty_document') {
        return { error: 'В PDF нет текста, который я могу прочитать. Пришлите нужную страницу скриншотом.' };
      }
      return { error: readFailed };
    }
    if (!response.ok) return { error: readFailed };
    const result = v.parse(documentText, await response.json());
    const limit = Math.min(12_000, Math.floor(contextWindow / 2));
    return { message: {
      kind: 'user',
      body: body + documentMarker + JSON.stringify({
        filename: attachment.filename, text: result.text.slice(0, limit),
        truncated: result.truncated || result.text.length > limit,
      }) + documentEnd,
    } };
  } catch {
    return { error: readFailed };
  }
}
