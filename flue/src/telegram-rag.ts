import * as v from 'valibot';

import { delivery } from './rag.js';

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

export type RagMessage = { text: string; html: string; needsHuman: boolean };

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
  if (!responses.length) return { text: ragUnavailable, html: `<p>${ragUnavailable}</p>`, needsHuman: true };

  let needsHuman = responses.length !== values.length || responses.some((response) =>
    response.status !== 'answered' || !response.parts.length || response.parts.some((item) => item.status !== 'supported'),
  );

  const sources = new Map(responses.flatMap((response) => response.sources).map((source) => [source.id, source]));
  const labels = new Map<string, number>();
  const paragraphs: string[] = [];
  for (const item of responses.flatMap((response) => response.parts)) {
    if (item.status === 'supported') {
      const ids = item.source_ids.filter((id) => sources.has(id));
      if (!ids.length || !item.statement.trim()) {
        needsHuman = true;
        continue;
      }
      for (const id of ids) if (!labels.has(id)) labels.set(id, labels.size + 1);
      paragraphs.push(`${item.statement} ${ids.map((id) => `[${labels.get(id)}]`).join(' ')}`);
    } else {
      paragraphs.push(item.clarification ||
        `По вопросу «${shorten(item.question, 170)}» в базе нет подтверждения.`);
    }
  }
  if (!paragraphs.length) paragraphs.push('В базе документации не нашлось подтверждённого ответа.');

  const html = paragraphs.map((text) => `<p>${escapeHtml(text)}</p>`);
  const plain = [...paragraphs];
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
      html.push('<p>Описание распознано с изображения.</p>');
      entry.push('Описание распознано с изображения.');
    } else if (source.quote) {
      html.push(`<blockquote>${escapeHtml(source.quote).replaceAll('\n', '<br>')}</blockquote>`);
      entry.push(`«${source.quote}»`);
    }
    plain.push(entry.filter(Boolean).join('\n'));
  }
  return { text: plain.join('\n\n'), html: html.join(''), needsHuman };
}
