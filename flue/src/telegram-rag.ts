import * as v from 'valibot';

import { delivery, needsRagClarification, type RagSource } from './rag.js';
import type { ReplyFlags } from './support-request.js';
import type { RichReplyBlock } from './telegram-output.js';
import type { RequestPhase } from './telegram-requests.js';

const ragUnavailable = 'Поиск по документации сейчас недоступен. Попробуйте чуть позже.';

function escapeHtml(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

function documentLink({ url: raw, page }: RagSource): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) {
      if (page && url.hash === `#page=${page}`) url.hash = '';
      return url.href;
    }
  } catch {}
  return null;
}

const indexedSourceId = /^([\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}):\d+(?::\d+:\d+)?$/u;

export type RagMessage = ReplyFlags & { text: string; blocks: RichReplyBlock[]; available: boolean };

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
    return {
      text, blocks: [{ html: `<p>${escapeHtml(text)}</p>` }], available: true,
      hasAnswer: false, hasClarification: true, phase, ...options,
    };
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

function documentTitle(raw: string): string {
  const stem = raw.replace(/\.pdf$/iu, '');
  const title = stem === raw ? raw : stem.replace(/_+/gu, ' ').trim();
  return shorten(title || raw, 250);
}

export function renderRag(...values: unknown[]): RagMessage {
  const responses = values.flatMap((value) => {
    const parsed = v.safeParse(delivery, value);
    return parsed.success && parsed.output.status !== 'unavailable' ? [parsed.output] : [];
  });
  if (!responses.length) return {
    text: ragUnavailable, blocks: [{ html: `<p>${ragUnavailable}</p>` }], available: false,
    hasAnswer: false, hasClarification: false,
  };

  const sources = new Map(responses.flatMap((response) => response.sources).map((source) => [source.id, source]));
  const citations = new Map<string, { title: string; link: string | null; sources: Map<string, RagSource> }>();
  const paragraphs: string[] = [];
  let missingEvidence = false;
  let hasAnswer = false;
  let hasClarification = false;
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
        for (const source of evidence) {
          const link = documentLink(source);
          const key = indexedSourceId.exec(source.id)?.[1] ?? source.file_id ?? link ?? source.id;
          let citation = citations.get(key);
          if (!citation) {
            citation = { title: source.title, link, sources: new Map() };
            citations.set(key, citation);
          }
          citation.link ??= link;
          citation.sources.set(source.id, source);
        }
        paragraphs.push(item.statement);
        hasAnswer = true;
      } else if (item.clarification.trim()) {
        paragraphs.push(item.clarification);
        hasClarification = true;
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

  const blocks: RichReplyBlock[] = paragraphs.map((text) => ({ html: `<p>${escapeHtml(text)}</p>` }));
  const plain = [...paragraphs];
  const seenImages = new Set<string>();
  for (const citation of citations.values()) {
    const title = documentTitle(citation.title);
    const { link } = citation;
    const name = escapeHtml(title);
    const label = link ? `<a href="${escapeHtml(link)}">${name}</a>` : name;
    blocks.push({ html: `<p><b>${label}</b></p>` });
    const entry = link ? [title, link] : [title];
    const locations = new Map<string, { quotes: Set<string>; images: string[] }>();
    for (const source of citation.sources.values()) {
      const location = source.page ? `стр. ${source.page}` : [
        shorten(source.section.join(' / '), 200),
        ...source.identifiers,
      ].filter(Boolean).join(' · ');
      let group = locations.get(location);
      if (!group) {
        group = { quotes: new Set(), images: [] };
        locations.set(location, group);
      }
      if (source.visual && source.image_key && !seenImages.has(source.image_key)) {
        seenImages.add(source.image_key);
        group.images.push(source.id);
      }
      if (!source.visual && source.quote) group.quotes.add(source.quote);
    }
    for (const [location, { quotes, images }] of locations) {
      if (!quotes.size && !images.length) continue;
      const headingHtml = location ? `<p><i>${escapeHtml(location)}</i></p>` : undefined;
      const html = [...quotes].map((quote) =>
        `<blockquote>${escapeHtml(quote).replaceAll('\n', '<br>')}</blockquote>`,
      ).join('');
      blocks.push({ html, headingHtml, images });
      if (!quotes.size) continue;
      if (location) entry.push(location);
      for (const quote of quotes) entry.push(`«${quote}»`);
    }
    plain.push(entry.join('\n'));
  }
  return {
    text: plain.join('\n\n'), blocks, available: true,
    hasAnswer, hasClarification,
  };
}
