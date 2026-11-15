import { AsyncLocalStorage } from 'node:async_hooks';

import { createOpenTelemetryInstrumentation } from '@flue/opentelemetry';
import { metrics, SpanStatusCode, trace } from '@opentelemetry/api';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { instrument, type FlueInstrumentation } from '@flue/runtime';

import { recordRequestModelUsage } from './request-pricing.js';
import type { DeliveryKind, DeliveryStatus } from './telegram-store.js';

const boundaries = [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 45, 60, 90, 120, 180, 300];
const durationOptions = { unit: 's', advice: { explicitBucketBoundaries: boundaries } };
const tracer = trace.getTracer('bars');
let instruments: ReturnType<typeof createInstruments> | undefined;
type Interval = { start: number; end: number };
type ReplyStages = { search: Interval[]; generation: Interval[] };
const replyStages = new Map<string, ReplyStages>();
const activeReplies = new Map<string, string>();
const ragContext = new AsyncLocalStorage<{ instanceId: string; stages?: ReplyStages }>();

function createInstruments() {
  const meter = metrics.getMeter('bars');
  return {
    tokens: meter.createCounter('bars.model.tokens'),
    modelDuration: meter.createHistogram('bars.model.duration', durationOptions),
    replyDuration: meter.createHistogram('bars.telegram.reply.duration', {
      unit: 's', advice: { explicitBucketBoundaries: [...boundaries, 600, 1800, 3600, 21600, 86400] },
    }),
    replyBreakdown: meter.createHistogram('bars.telegram.reply.stage.duration', durationOptions),
    deliveryCount: meter.createCounter('bars.telegram.delivery.count'),
    ragDuration: meter.createHistogram('bars.rag.step.duration', durationOptions),
  };
}

export function startTelemetry(): () => Promise<void> {
  const enabled = process.env.OTEL_EXPORTER_OTLP_ENDPOINT && process.env.OTEL_SDK_DISABLED !== 'true';
  const sdk = enabled ? new NodeSDK({ serviceName: process.env.OTEL_SERVICE_NAME || 'bars-flue' }) : undefined;
  sdk?.start();
  instruments = sdk ? createInstruments() : undefined;
  const otel = sdk ? createOpenTelemetryInstrumentation({ content: false }) : undefined;
  const dispose = instrument({
    interceptor(operation, ctx, next) {
      const run = () => otel ? otel.interceptor(operation, ctx, next) : next();
      if (operation.type === 'tool' && operation.toolName === 'answer_from_docs'
        && ctx.agentName === 'Bars' && ctx.instanceId) {
        const submissionId = ctx.submissionId ?? activeReplies.get(ctx.instanceId);
        return ragContext.run({ instanceId: ctx.instanceId, stages: submissionId ? replyStages.get(submissionId) : undefined }, run);
      }
      return run();
    },
    observe(event, ctx) {
      observeTurn(event);
      return otel?.observe(event, ctx);
    },
    dispose: () => otel?.dispose(),
  });
  return async () => {
    try {
      await dispose();
    } finally {
      instruments = undefined;
      replyStages.clear();
      activeReplies.clear();
      await sdk?.shutdown();
    }
  };
}

function observeTurn(event: Parameters<FlueInstrumentation['observe']>[0]): void {
  if (instruments && event.agentName === 'Bars' && event.instanceId) {
    const { instanceId } = event;
    if (event.type === 'submission_running' && event.kind === 'dispatch' && event.attemptCount === 1) {
      const { submissionId } = event;
      replyStages.set(submissionId, { search: [], generation: [] });
      activeReplies.set(instanceId, submissionId);
      setTimeout(() => {
        replyStages.delete(submissionId);
        if (activeReplies.get(instanceId) === submissionId) activeReplies.delete(instanceId);
      }, 5 * 60_000).unref();
    } else if (event.type === 'submission_settled') {
      if (activeReplies.get(instanceId) === event.submissionId) activeReplies.delete(instanceId);
      if (event.outcome !== 'completed') replyStages.delete(event.submissionId);
    }
  }
  if (event.type !== 'turn') return;
  const attributes = {
    workload: event.agentName === 'DocumentImport' ? 'document_import' : 'chat',
    model: event.request.requestedModel,
  };
  instruments?.modelDuration.record(event.durationMs / 1000, attributes);
  const rag = ragContext.getStore();
  if (event.agentName === 'Bars') {
    const stages = event.submissionId ? replyStages.get(event.submissionId) : rag?.stages;
    const end = Date.parse(event.timestamp);
    stages?.generation.push({ start: end - event.durationMs, end });
  }
  const usage = event.response.usage;
  const instanceId = event.agentName === 'Bars' ? rag?.instanceId ?? (event.submissionId && event.instanceId) : undefined;
  if (instanceId) recordRequestModelUsage(instanceId, event.turnId, event.timestamp, attributes.model, usage);
  if (!usage) return;
  instruments?.tokens.add(usage.input + usage.cacheRead + usage.cacheWrite, { ...attributes, direction: 'input' });
  instruments?.tokens.add(usage.output, { ...attributes, direction: 'output' });
}

export function recordDelivery(kind: DeliveryKind, status: DeliveryStatus): void {
  instruments?.deliveryCount.add(1, { kind, status });
}

function coveredTime(intervals: Interval[], from: number, to: number): number {
  let cursor = from;
  let total = 0;
  for (const interval of intervals.sort((left, right) => left.start - right.start)) {
    const start = Math.max(cursor, interval.start);
    const end = Math.min(to, interval.end);
    if (end <= start) continue;
    total += end - start;
    cursor = end;
  }
  return total;
}

export function recordReplyDuration(submissionId: string, received: Date, processing: Date, sending: number, sent: number): void {
  if (!instruments) return;
  const { replyDuration, replyBreakdown } = instruments;
  const startedAt = Math.max(processing.getTime(), received.getTime());
  const sendStartedAt = Math.max(sending, startedAt);
  const finishedAt = Math.max(sent, sendStartedAt);
  replyDuration.record((finishedAt - received.getTime()) / 1000, { stage: 'total' });
  replyDuration.record((startedAt - received.getTime()) / 1000, { stage: 'queue' });
  replyDuration.record((sendStartedAt - startedAt) / 1000, { stage: 'preparation' });
  replyDuration.record((finishedAt - sendStartedAt) / 1000, { stage: 'delivery' });
  const stages = replyStages.get(submissionId);
  if (!stages) return;
  replyStages.delete(submissionId);
  const search = coveredTime(stages.search, startedAt, sendStartedAt);
  const occupied = coveredTime([...stages.search, ...stages.generation], startedAt, sendStartedAt);
  const breakdown = {
    total: finishedAt - received.getTime(),
    queue: startedAt - received.getTime(),
    preparation: sendStartedAt - startedAt - occupied,
    search,
    generation: occupied - search,
    delivery: finishedAt - sendStartedAt,
  };
  for (const [stage, duration] of Object.entries(breakdown)) replyBreakdown.record(duration / 1000, { stage });
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
      const finished = performance.now();
      ragDuration.record((finished - started) / 1000, { step });
      if (step === 'search') ragContext.getStore()?.stages?.search.push({
        start: performance.timeOrigin + started, end: performance.timeOrigin + finished,
      });
      span.end();
    }
  });
}
