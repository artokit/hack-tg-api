import * as v from 'valibot';

import { delivery, needsRagClarification, type RagSource } from './rag.js';
import type { RequestPhase } from './telegram-requests.js';

const ragUnavailable = 'Поиск по документации сейчас недоступен. Попробуйте чуть позже.';

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

export function supportRagReply(values: unknown[], previous: RequestPhase): RagMessage & {
  phase: RequestPhase;
  followUp?: string;
  offerSupport?: true;
} {
  const results = values.flatMap((value) => {
    const parsed = v.safeParse(delivery, value);
    return parsed.success ? [parsed.output] : [];
  });
  const result = results[results.length - 1];
  if (!result || result.status === 'unavailable' || !needsRagClarification(result)) {
    const phase = result?.status === 'answered' ? 'answer' : 'technical';
    return { ...renderRag(...results), phase };
  }
  const focused = result.not_found_reply?.endsWith('?') ? result.not_found_reply : undefined;
  const question = result.parts.find((part) => part.status === 'ambiguous' && part.clarification)?.clarification ?? focused;
  const offerSupport = previous === 'clarification' || previous === 'handoff_confirmation' || !question;
  const phase = offerSupport ? 'handoff_confirmation' : 'clarification';
  const supported = result.parts.filter((part) => part.status === 'supported');
  const text = offerSupport
    ? supported.length
      ? 'По оставшейся части ответа в документации нет. Передать вопрос специалисту?'
      : 'Точного ответа в документации не нашлось. Передать вопрос специалисту?'
    : question;
  const options = offerSupport ? { offerSupport: true as const } : {};
  if (!supported.length) {
    return { text, html: `<p>${escapeHtml(text)}</p>`, available: true, images: [], phase, ...options };
  }
  return {
    ...renderRag({ ...result, status: 'answered', parts: supported }),
    phase, followUp: text, ...options,
  };
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
  const citations = new Map<string, { ordinal: number; source: RagSource; quotes: Set<string> }>();
  const paragraphs: string[] = [];
  let missingEvidence = false;
  for (const response of responses) {
    if (response.status === 'not_found' && response.not_found_reply) {
      paragraphs.push(response.not_found_reply);
      continue;
    }
    for (const item of response.parts) {
      if (item.status === 'supported') {
        const evidence = item.source_ids.flatMap((id) => sources.get(id) ?? []);
        if (!evidence.length || !item.statement.trim()) {
          missingEvidence = true;
          continue;
        }
        const labels = new Set<string>();
        for (const source of evidence) {
          const key = source.url && !source.visual
            ? JSON.stringify([source.url, source.title, source.page, source.section, source.identifiers])
            : source.id;
          let citation = citations.get(key);
          if (!citation) {
            citation = { ordinal: citations.size + 1, source, quotes: new Set() };
            citations.set(key, citation);
          }
          if (source.quote) citation.quotes.add(source.quote);
          labels.add(`[${citation.ordinal}]`);
        }
        paragraphs.push(`${item.statement} ${[...labels].join(' ')}`);
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
  for (const { source, ordinal, quotes } of citations.values()) {
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
    } else if (quotes.size) {
      const excerpts = [...quotes].join('\n…\n');
      html.push(`<blockquote>${escapeHtml(excerpts).replaceAll('\n', '<br>')}</blockquote>`);
      entry.push(`«${excerpts}»`);
    }
    plain.push(entry.filter(Boolean).join('\n'));
  }
  return { text: plain.join('\n\n'), html: html.join(''), available: true, images: [...images.values()] };
}
