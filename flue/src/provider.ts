import { createProvider, type ProviderRequestOptions } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';

import { httpUrl, required } from './config.js';

export const modelId = required('CHAT_MODEL');
export const contextWindow = Number(required('CHAT_CONTEXT_WINDOW'));
if (!Number.isSafeInteger(contextWindow) || contextWindow < 1024) {
  throw new Error('CHAT_CONTEXT_WINDOW must be an integer of at least 1024');
}

const apiKey = process.env.CHAT_API_KEY?.trim();
const baseUrl = httpUrl('CHAT_BASE_URL');
const documentModelId = `${modelId}:documents`;
export const ragModelId = `bars-chat/${documentModelId}`;
const providerHost = new URL(baseUrl).hostname;
const openrouter = providerHost === 'openrouter.ai';
const directLuna = providerHost === 'api.openai.com' && modelId === 'gpt-6-luna';

const api = openAICompletionsApi();
const requestLimits = { timeoutMs: 20_000, maxRetries: 0 };
const chatModel = {
  id: modelId,
  name: modelId,
  api: 'openai-completions' as const,
  provider: 'bars-chat',
  baseUrl,
  reasoning: false,
  input: ['text' as const, 'image' as const],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow,
  maxTokens: Math.min(Math.floor(contextWindow / 8), 1600),
};

function requestOptions<T extends ProviderRequestOptions>(model: string, options: T | undefined) {
  const documents = model === documentModelId;
  if (!documents && !directLuna) return { ...options, ...requestLimits };
  return {
    ...options,
    ...requestLimits,
    async onPayload(payload: unknown, model: Parameters<NonNullable<T['onPayload']>>[1]) {
      const transformed = await options?.onPayload?.(payload, model);
      return {
        ...((transformed ?? payload) as Record<string, unknown>),
        ...(documents ? { model: modelId } : {}),
        ...(documents && openrouter ? { provider: { data_collection: 'deny', zdr: true } } : {}),
        ...(directLuna ? { reasoning_effort: 'none' } : {}),
      };
    },
  };
}

export const provider = createProvider({
  id: 'bars-chat',
  auth: {
    apiKey: {
      name: 'БАРС Chat Completions',
      resolve: async () => ({
        auth: {
          apiKey: apiKey || 'keyless',
          headers: {
            ...(apiKey ? {} : { Authorization: null }),
            'OpenAI-Organization': null,
            'OpenAI-Project': null,
          },
        },
      }),
    },
  },
  models: [chatModel, {
    ...chatModel,
    id: documentModelId,
    maxTokens: Math.min(Math.floor(contextWindow / 2), 4200),
  }],
  api: {
    stream: (model, context, options) => api.stream(model, context, requestOptions(model.id, options)),
    streamSimple: (model, context, options) => api.streamSimple(model, context, requestOptions(model.id, options)),
  },
});
