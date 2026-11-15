import { createOpenTelemetryInstrumentation } from '@flue/opentelemetry';
import { metrics, SpanStatusCode, trace } from '@opentelemetry/api';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { instrument, observe } from '@flue/runtime';

import type { DeliveryKind, DeliveryStatus } from './telegram-store.js';

const boundaries = [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 45, 60, 90, 120, 180, 300];
const durationOptions = { unit: 's', advice: { explicitBucketBoundaries: boundaries } };
const tracer = trace.getTracer('bars');
let instruments: ReturnType<typeof createInstruments> | undefined;

function createInstruments() {
  const meter = metrics.getMeter('bars');
  return {
    tokens: meter.createCounter('bars.model.tokens'),
    modelDuration: meter.createHistogram('bars.model.duration', durationOptions),
    replyDuration: meter.createHistogram('bars.telegram.reply.duration', {
      unit: 's', advice: { explicitBucketBoundaries: [...boundaries, 600, 1800, 3600, 21600, 86400] },
    }),
    deliveryCount: meter.createCounter('bars.telegram.delivery.count'),
    ragDuration: meter.createHistogram('bars.rag.step.duration', durationOptions),
  };
}

export function startTelemetry(): () => Promise<void> {
  if (!process.env.OTEL_EXPORTER_OTLP_ENDPOINT || process.env.OTEL_SDK_DISABLED === 'true') {
    return async () => {};
  }
  const sdk = new NodeSDK({ serviceName: process.env.OTEL_SERVICE_NAME || 'bars-flue' });
  sdk.start();
  instruments = createInstruments();
  const { modelDuration, tokens } = instruments;
  const dispose = instrument(createOpenTelemetryInstrumentation({ content: false }));
  const stopCounting = observe((event) => {
    if (event.type !== 'turn') return;
    const attributes = {
      workload: event.agentName === 'DocumentImport' ? 'document_import' : 'chat',
      model: event.request.requestedModel,
    };
    modelDuration.record(event.durationMs / 1000, attributes);
    const usage = event.response.usage;
    if (!usage) return;
    tokens.add(usage.input + usage.cacheRead + usage.cacheWrite, { ...attributes, direction: 'input' });
    tokens.add(usage.output, { ...attributes, direction: 'output' });
  });
  return async () => {
    stopCounting();
    try {
      await dispose();
    } finally {
      instruments = undefined;
      await sdk.shutdown();
    }
  };
}

export function recordDelivery(kind: DeliveryKind, status: DeliveryStatus): void {
  instruments?.deliveryCount.add(1, { kind, status });
}

export function recordReplyDuration(received: Date, processing: Date, sending: number, sent: number): void {
  if (!instruments) return;
  const { replyDuration } = instruments;
  const startedAt = Math.max(processing.getTime(), received.getTime());
  const sendStartedAt = Math.max(sending, startedAt);
  const finishedAt = Math.max(sent, sendStartedAt);
  replyDuration.record((finishedAt - received.getTime()) / 1000, { stage: 'total' });
  replyDuration.record((startedAt - received.getTime()) / 1000, { stage: 'queue' });
  replyDuration.record((sendStartedAt - startedAt) / 1000, { stage: 'preparation' });
  replyDuration.record((finishedAt - sendStartedAt) / 1000, { stage: 'delivery' });
}

export function measureRag<T>(step: 'search' | 'compose', run: () => Promise<T>): Promise<T> {
  if (!instruments) return run();
  const { ragDuration } = instruments;
  return tracer.startActiveSpan(`bars.rag.${step}`, async (span) => {
    const started = performance.now();
    try {
      return await run();
    } catch (error) {
      span.setStatus({ code: SpanStatusCode.ERROR });
      throw error;
    } finally {
      ragDuration.record((performance.now() - started) / 1000, { step });
      span.end();
    }
  });
}
