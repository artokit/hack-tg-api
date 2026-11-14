import { createModels, createProvider, type ImageContent } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';

import { httpUrl, required } from './config.js';

export const modelId = required('CHAT_MODEL');
export const contextWindow = Number(required('CHAT_CONTEXT_WINDOW'));
if (!Number.isSafeInteger(contextWindow) || contextWindow < 1024) {
  throw new Error('CHAT_CONTEXT_WINDOW must be an integer of at least 1024');
}

const apiKey = process.env.CHAT_API_KEY?.trim();
const baseUrl = httpUrl('CHAT_BASE_URL');

const api = openAICompletionsApi();
const requestLimits = { timeoutMs: 20_000, maxRetries: 0 };

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
  models: [{
    id: modelId,
    name: modelId,
    api: 'openai-completions',
    provider: 'bars-chat',
    baseUrl,
    reasoning: false,
    input: ['text', 'image'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow,
    maxTokens: Math.min(Math.floor(contextWindow / 8), 1600),
  }],
  api: {
    stream: (model, context, options) => api.stream(model, context, { ...options, ...requestLimits }),
    streamSimple: (model, context, options) => api.streamSimple(model, context, { ...options, ...requestLimits }),
  },
});

const models = createModels();
models.setProvider(provider);
const chatModel = provider.getModels()[0];
const openrouter = new URL(baseUrl).hostname === 'openrouter.ai';

export async function runModel(
  instructions: string, text: string, signal: AbortSignal, maxTokens: number, image?: ImageContent,
): Promise<string> {
  const result = await models.completeSimple(chatModel, {
    systemPrompt: instructions,
    messages: [{
      role: 'user',
      timestamp: Date.now(),
      content: image ? [{ type: 'text', text }, image] : text,
    }],
  }, {
    signal,
    maxTokens: Math.min(maxTokens, Math.floor(contextWindow / 2)),
    ...(openrouter ? {
      onPayload(payload: unknown) {
        return {
          ...(payload as Record<string, unknown>),
          provider: { data_collection: 'deny', zdr: true },
        };
      },
    } : {}),
  });
  if (result.stopReason !== 'stop') throw new Error('Model did not return a complete response');
  return result.content.flatMap((part) => part.type === 'text' ? [part.text] : []).join('').trim();
}
