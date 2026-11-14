import { defineTool } from '@flue/runtime';
import * as v from 'valibot';

import { httpUrl, required } from './config.js';

export const ragEnabled = /^(?:1|true|yes|on)$/i.test(process.env.RAG_ENABLED?.trim() ?? '');
export const ragToolName = 'answer_from_docs';
export const ragUnavailable = 'Поиск по документации сейчас недоступен. Попробуй ещё раз чуть позже.';

const exactId = /(?<![\w.-])[A-Z]{1,10}-\d+(?:\.\d+)*-\d{2,6}(?![\w-]|\.\d)/i;
const barsTerm = /(?:(?<![а-яё])БАРС(?![а-яё])|реестр[а-яё]*\s+(?:мебели|техники)|БП\s*[«"„]?Командировка|Служебная информация|производственн[а-яё]+\s+календар[а-яё]*|mainmenuitemclick|!>\s*\d)/iu;
const internalDocs = /(?:(?:наш[а-яё]*|внутренн[а-яё]*|корпоративн[а-яё]*)\s+(?:баз[а-яё]*|регламент[а-яё]*|документац[а-яё]*|инструкц[а-яё]*|процедур[а-яё]*)|(?:оформить|согласовать|оплатить|отправить)\s+командировк[а-яё]*)/iu;

export function requiresRag(question: string): boolean {
  return exactId.test(question) || barsTerm.test(question) || internalDocs.test(question);
}

const source = v.object({
  id: v.string(),
  title: v.string(),
  url: v.nullable(v.string()),
  page: v.nullable(v.number()),
  section: v.array(v.string()),
  identifiers: v.optional(v.array(v.string()), []),
  quote: v.nullable(v.string()),
  visual: v.boolean(),
});
const part = v.object({
  question: v.string(),
  status: v.picklist(['supported', 'ambiguous', 'unsupported']),
  statement: v.string(),
  source_ids: v.array(v.string()),
  clarification: v.string(),
});
const answer = v.object({
  status: v.picklist(['answered', 'partial', 'clarify', 'not_found']),
  parts: v.array(part),
  sources: v.array(source),
});
const delivery = v.union([answer, v.object({ status: v.literal('unavailable') })]);
type RagDelivery = v.InferOutput<typeof delivery>;
type RagSource = v.InferOutput<typeof source>;

export function answerTool(question: string, write: (data: RagDelivery) => void) {
  return defineTool({
    name: ragToolName,
    timeoutMs: 55_000,
    description: 'Ответь по базе документации БАРС на вопросы о внутренних правилах, интерфейсах, процессах и конкретных пунктах. Передай самостоятельный запрос, если пользователь уточняет предыдущий вопрос.',
    input: v.object({
      standalone_question: v.optional(v.pipe(v.string(), v.trim(), v.minLength(1), v.maxLength(1600))),
    }),
    async run({ data, signal }) {
      let result: RagDelivery;
      try {
        const timeout = AbortSignal.timeout(53_000);
        const response = await fetch(`${httpUrl('API_URL')}/internal/rag/answer`, {
          method: 'POST',
          signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${required('RAG_SERVICE_TOKEN')}`,
          },
          body: JSON.stringify({ question, standalone_question: data.standalone_question }),
        });
        if (!response.ok) throw new Error(`RAG API status ${response.status}`);
        result = v.parse(answer, await response.json());
      } catch (error) {
        if (signal?.aborted) throw error;
        console.warn('RAG tool unavailable', error instanceof Error ? error.name : 'Error');
        result = { status: 'unavailable' };
      }
      write(result);
      return {
        output: {
          status: result.status,
          parts: result.status === 'unavailable' ? [] : result.parts,
        },
        terminate: true,
      };
    },
  });
}

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

function renderCompactRag(response: v.InferOutput<typeof answer>, sources: Map<string, RagSource>): string {
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
