import { randomUUID } from 'node:crypto';
import type { Agent, FlueHarness } from '@flue/runtime';
import { createFlueContext, resolveModel } from '@flue/runtime/internal';

export const transientSignal = 'transient-rag';

export async function withTransientHarness<T>(
  agent: Agent,
  initialData: unknown,
  run: (harness: FlueHarness) => Promise<T>,
): Promise<T> {
  const context = createFlueContext({
    id: randomUUID(),
    agentName: agent.name,
    env: process.env,
    agentConfig: { resolveModel, compaction: false },
  });
  const harness = await context.initializeRootHarness(
    agent, { kind: 'signal', type: transientSignal, body: '' }, initialData,
  );
  try {
    return await run(harness);
  } finally {
    await harness.close();
  }
}
