import * as v from 'valibot';

import { delivery, type RagDelivery, type RagSource } from './rag.js';

const ragUnavailable = 'Поиск по документации сейчас недоступен. Попробуй ещё раз чуть позже.';

function escapeMarkdown(text: string): string {
  return text.replace(/[&<>"'\\`*_{}\[\]()#+\-!.|]/g, '\\$&');
}

function originalLink(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) {
      return url.href.replace(/[()]/g, (value) => value === '(' ? '%28' : '%29');
    }
  } catch {}
  return null;
}

function shorten(text: string, length: number): string {
  if (text.length <= length) return text;
  let end = length - 1;
  const code = text.charCodeAt(end - 1);
  if (code >= 0xd800 && code <= 0xdbff) end--;
  return text.slice(0, end) + '…';
}

export function renderRag(...values: unknown[]): string {
  const responses = values.flatMap((value) => {
    const parsed = v.safeParse(delivery, value);
    return parsed.success && parsed.output.status !== 'unavailable' ? [parsed.output] : [];
  });
  if (!responses.length) return ragUnavailable;
  const response = {
    status: responses.at(-1)!.status,
    parts: responses.flatMap((item) => item.parts),
    sources: responses.flatMap((item) => item.sources),
  };
  const sources = new Map(response.sources.map((item) => [item.id, item]));
  const paragraphs: string[] = [];
  const labels = new Map<string, number>();
  for (const item of response.parts) {
    if (item.status === 'supported') {
      const ids = item.source_ids.filter((id) => sources.has(id));
      if (!ids.length || !item.statement.trim()) continue;
      for (const id of ids) if (!labels.has(id)) labels.set(id, labels.size + 1);
      const refs = ids.map((id) => `[${labels.get(id)}]`).join(' ');
      paragraphs.push(`${escapeMarkdown(item.statement)} ${escapeMarkdown(refs)}`);
    } else if (item.clarification) {
      paragraphs.push(escapeMarkdown(item.clarification));
    } else if (response.parts.length > 1 || response.status !== 'clarify') {
      const question = item.question.slice(0, 170);
      paragraphs.push(`По вопросу «${escapeMarkdown(question)}» в базе нет подтверждения.`);
    }
  }
  if (!paragraphs.length) paragraphs.push('В базе документации не нашлось подтверждённого ответа.');
  const evidence = [];
  for (const [id, ordinal] of labels) {
    const item = sources.get(id)!;
    const location = item.page ? `стр. ${item.page}` : item.section.join(' / ');
    const title = escapeMarkdown([item.title, location, ...item.identifiers].filter(Boolean).join(', '));
    const link = originalLink(item.url);
    const label = link ? `[${title}](${link})` : title;
    const excerpt = item.visual
      ? 'Описание распознано с изображения.'
      : item.quote && `«${escapeMarkdown(item.quote)}»`;
    evidence.push(`${ordinal}\\. ${label}${excerpt ? `\n${excerpt}` : ''}`);
  }
  const full = [...paragraphs, ...evidence].join('\n\n');
  return full.length <= 4000 ? full : renderCompactRag(response, sources);
}

function renderCompactRag(response: Exclude<RagDelivery, { status: 'unavailable' }>, sources: Map<string, RagSource>): string {
  const lines: string[] = [];
  const parts = response.parts.slice(-6);
  const perPart = Math.floor(3960 / parts.length);
  for (const item of parts) {
    const itemSource = item.source_ids.map((id) => sources.get(id)).find((value) => value);
    if (item.status !== 'supported' || !itemSource) {
      lines.push(escapeMarkdown(shorten(item.clarification || 'Для части вопроса нет подтверждения.', 110)));
      continue;
    }
    const label = escapeMarkdown(shorten(
      [itemSource.title, itemSource.page ? `стр. ${itemSource.page}` : itemSource.section.join(' / ')]
        .filter(Boolean).join(', '), 54,
    ));
    const link = originalLink(itemSource.url);
    const sourceLabel = link && link.length <= Math.floor(perPart / 3) ? `[${label}](${link})` : label;
    const excerpt = itemSource.visual ? 'По изображению.' : itemSource.quote;
    const quote = excerpt ? escapeMarkdown(shorten(excerpt, 65)) : '';
    const available = Math.floor((perPart - sourceLabel.length - quote.length - 2) / 2);
    lines.push([
      escapeMarkdown(shorten(item.statement, Math.max(20, available))), sourceLabel, quote,
    ].filter(Boolean).join('\n'));
  }
  return lines.join('\n\n');
}
