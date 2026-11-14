import { createProvider } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';

import { httpUrl, required } from './config.js';

export const modelId = required('CHAT_MODEL');
export const contextWindow = Number(required('CHAT_CONTEXT_WINDOW'));
if (!Number.isSafeInteger(contextWindow) || contextWindow < 1024) {
  throw new Error('CHAT_CONTEXT_WINDOW must be an integer of at least 1024');
}

const apiKey = process.env.CHAT_API_KEY?.trim();

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
    baseUrl: httpUrl('CHAT_BASE_URL'),
    reasoning: false,
    input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow,
    maxTokens: Math.min(Math.floor(contextWindow / 8), 1600),
  }],
  api: {
    stream: (model, context, options) => api.stream(model, context, { ...options, ...requestLimits }),
    streamSimple: (model, context, options) => api.streamSimple(model, context, { ...options, ...requestLimits }),
  },
});
