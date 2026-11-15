import * as v from 'valibot';

import { delivery, needsRagClarification, type RagDelivery } from './rag.js';
import type { RequestPhase } from './telegram-requests.js';

const ragUnavailable = 'Поиск по документации сейчас недоступен. Попробуй ещё раз чуть позже.';

function escapeHtml(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

function originalLink(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url.href;
  } catch {}
  return null;
}

export type RagMessage = { text: string; html: string; available: boolean; images: string[] };

export function supportRagReply(values: unknown[]): RagMessage & { phase: RequestPhase } {
  const results = values.flatMap((value) => {
    const parsed = v.safeParse(delivery, value);
    return parsed.success ? [parsed.output] : [];
  });
  const result = results[results.length - 1];
  if (result && result.status !== 'unavailable' && needsRagClarification(result)) {
    return { ...renderClarification(result), phase: 'clarification' };
  }
  const phase = !result || result.status === 'unavailable' || result.search_incomplete ? 'technical' : 'answer';
  return { ...renderRag(...results), phase };
}

export function supportedRagReply(values: unknown[]): RagMessage | undefined {
  const supported = values.flatMap((value) => {
    const parsed = v.safeParse(delivery, value);
    if (!parsed.success || parsed.output.status === 'unavailable') return [];
    const parts = parsed.output.parts.filter((part) => part.status === 'supported');
    return parts.length ? [{ ...parsed.output, status: 'answered', parts }] : [];
  });
  return supported.length ? renderRag(...supported) : undefined;
}

function renderClarification(result: Exclude<RagDelivery, { status: 'unavailable' }>): RagMessage {
  const focused = result.not_found_reply?.endsWith('?') ? result.not_found_reply : undefined;
  const question = result.parts.find((part) => part.status === 'ambiguous' && part.clarification)?.clarification
    ?? focused
    ?? 'Уточни, пожалуйста, в каком разделе или при каком действии возник вопрос?';
  const supported = result.parts.filter((part) => part.status === 'supported');
  if (!supported.length) return { text: question, html: `<p>${escapeHtml(question)}</p>`, available: true, images: [] };
  const answer = renderRag({ ...result, status: 'answered', parts: supported });
  return { ...answer, text: `${answer.text}\n\n${question}`, html: `${answer.html}<p>${escapeHtml(question)}</p>` };
}

function shorten(text: string, length: number): string {
  if (text.length <= length) return text;
  let end = length - 1;
  const code = text.charCodeAt(end - 1);
  if (code >= 0xd800 && code <= 0xdbff) end--;
  return text.slice(0, end) + '…';
}

export function renderRag(...values: unknown[]): RagMessage {
  const responses = values.flatMap((value) => {
    const parsed = v.safeParse(delivery, value);
    return parsed.success && parsed.output.status !== 'unavailable' ? [parsed.output] : [];
  });
  if (!responses.length) return { text: ragUnavailable, html: `<p>${ragUnavailable}</p>`, available: false, images: [] };

  const sources = new Map(responses.flatMap((response) => response.sources).map((source) => [source.id, source]));
  const labels = new Map<string, number>();
  const paragraphs: string[] = [];
  let missingEvidence = false;
  for (const response of responses) {
    if (response.status === 'not_found' && response.not_found_reply) {
      paragraphs.push(response.not_found_reply);
      continue;
    }
    for (const item of response.parts) {
      if (item.status === 'supported') {
        const ids = item.source_ids.filter((id) => sources.has(id));
        if (!ids.length || !item.statement.trim()) {
          missingEvidence = true;
          continue;
        }
        for (const id of ids) if (!labels.has(id)) labels.set(id, labels.size + 1);
        paragraphs.push(`${item.statement} ${ids.map((id) => `[${labels.get(id)}]`).join(' ')}`);
      } else if (item.clarification.trim()) {
        paragraphs.push(item.clarification);
      } else {
        missingEvidence = true;
      }
    }
  }
  if (!paragraphs.length) {
    paragraphs.push('В базе знаний не нашлось ответа.');
  } else if (missingEvidence) {
    paragraphs.push('По остальным пунктам ответа в базе знаний нет.');
  }

  const html = paragraphs.map((text) => `<p>${escapeHtml(text)}</p>`);
  const plain = [...paragraphs];
  const images = new Map<string, string>();
  for (const [id, ordinal] of labels) {
    const source = sources.get(id)!;
    const title = shorten(source.title, 250);
    const location = [
      source.page ? `стр. ${source.page}` : '',
      shorten(source.section.join(' / '), 200),
      ...source.identifiers,
    ].filter(Boolean).join(' · ');
    const link = originalLink(source.url);
    const name = escapeHtml(title);
    const label = link ? `<a href="${escapeHtml(link)}">${name}</a>` : name;
    const placement = location ? ` · ${escapeHtml(location)}` : '';
    html.push(`<p>${ordinal}. <b>${label}</b>${placement}</p>`);
    const entry = [`${ordinal}. ${title}${location ? ` · ${location}` : ''}`, link];
    if (source.visual) {
      if (source.image_key && !images.has(source.image_key)) images.set(source.image_key, source.id);
      html.push('<p>Описание распознано с изображения.</p>');
      entry.push('Описание распознано с изображения.');
    } else if (source.quote) {
      html.push(`<blockquote>${escapeHtml(source.quote).replaceAll('\n', '<br>')}</blockquote>`);
      entry.push(`«${source.quote}»`);
    }
    plain.push(entry.filter(Boolean).join('\n'));
  }
  return { text: plain.join('\n\n'), html: html.join(''), available: true, images: [...images.values()] };
}
