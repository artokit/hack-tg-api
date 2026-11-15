import type { ImageContent } from '@earendil-works/pi-ai';
import type { Agent } from '@flue/runtime';
import * as v from 'valibot';

import { httpUrl, required } from './config.js';
import { ragModelId } from './provider.js';
import { ragPrompts } from './rag-prompts.js';
import type { Evidence } from './rag.js';
import { withTransientHarness } from './transient-harness.js';

const visualSelection = v.object({ ids: v.pipe(v.array(v.nullable(v.string())), v.maxLength(6)) });
const maxVisualText = 420;

type VisualPart = { index: number; question: string; evidence: Evidence[] };

export function asksAboutAppearance(question: string): boolean {
  return /(?:^|[^\p{L}])(?:цвет|скрин|подсвеч|выгляд|выделен|пиктограмм|иконк)\p{L}*/iu.test(question)
    || /(?:кнопк|значок)/iu.test(question) && /(?:расположен|где на форме|где на экране|какого вида)/iu.test(question);
}

function visualCandidates(evidence: Evidence[], limit: number) {
  const areas = new Map<string, { id: string; title: string; page: number | null; label: string; text: string }>();
  const ranked = evidence.toSorted((a, b) =>
    (a.visual_rank ?? Number.MAX_SAFE_INTEGER) - (b.visual_rank ?? Number.MAX_SAFE_INTEGER));
  for (const block of ranked) {
    if (!block.image_key) continue;
    const key = block.image_key;
    const existing = areas.get(key);
    const text = [...block.columns, block.text].filter(Boolean).join(' | ');
    if (existing) {
      if (existing.text.length < maxVisualText && !existing.text.includes(text)) {
        existing.text = (existing.text + '\n' + text).slice(0, maxVisualText);
      }
    } else if (areas.size < limit) {
      areas.set(key, {
        id: block.id, title: block.title, page: block.page,
        text: text.slice(0, maxVisualText), label: block.label.slice(0, 200),
      });
    }
  }
  return [...areas.values()];
}

export async function fetchRagImage(id: string, signal?: AbortSignal, telegram = false): Promise<Buffer | undefined> {
  const timeout = AbortSignal.timeout(10_000);
  const query = telegram ? '?telegram=true' : '';
  try {
    const response = await fetch(`${httpUrl('API_URL')}/internal/rag/visual/${encodeURIComponent(id)}${query}`, {
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      headers: { 'X-Bot-Token': required('BOT_API_TOKEN') },
    });
    if (!response.ok || response.headers.get('content-type') !== 'image/png') return;
    return Buffer.from(await response.arrayBuffer());
  } catch (error) {
    signal?.throwIfAborted();
    console.warn('RAG image unavailable', error instanceof Error ? error.name : 'Error');
  }
}

export async function selectVisuals(agent: Agent, parts: VisualPart[], signal: AbortSignal) {
  const images: ImageContent[] = [];
  const byPart = new Map<number, { id: string; image_number: number }>();
  const limit = Math.min(12, Math.floor(18 / Math.max(1, parts.length)));
  const candidates = parts.map(({ evidence, ...part }) => ({
    ...part, candidates: visualCandidates(evidence, limit),
  })).filter((part) => part.candidates.length);
  if (!candidates.length) return { images, byPart };

  let ids: (string | null)[];
  try {
    const result = await withTransientHarness(agent, undefined, (harness) => harness.prompt(
      ragPrompts.select_visual + '\n' + JSON.stringify(candidates),
      { model: ragModelId, result: visualSelection, signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]) },
    ));
    ids = result.data.ids;
  } catch (error) {
    signal.throwIfAborted();
    console.warn('RAG image selection unavailable', error instanceof Error ? error.name : 'Error');
    return { images, byPart };
  }
  if (ids.length !== candidates.length) return { images, byPart };

  const chosen = candidates.flatMap(({ index, candidates: options }, position) => {
    const id = ids[position];
    return id !== null && options.some((candidate) => candidate.id === id) ? [{ index, id }] : [];
  });
  const uniqueIds = [...new Set(chosen.map(({ id }) => id))];
  const loaded = await Promise.all(uniqueIds.map((id) => fetchRagImage(id, signal)));
  const imageNumbers = new Map<string, number>();
  for (const [position, image] of loaded.entries()) {
    if (image) imageNumbers.set(uniqueIds[position], images.push({
      type: 'image', mimeType: 'image/png', data: image.toString('base64'),
    }));
  }
  for (const { index, id } of chosen) {
    const image_number = imageNumbers.get(id);
    if (image_number !== undefined) byPart.set(index, { id, image_number });
  }
  return { images, byPart };
}
