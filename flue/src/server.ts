import { start } from '@flue/runtime/node';
import { serve } from '@hono/node-server';

import app, { worker } from './app.js';
import { Bars } from './agents/bars.js';
import { SupportRequestFinalizer } from './agents/support-request-finalizer.js';
import db from './db.js';
import { provider } from './provider.js';
import { startTelemetry } from './telemetry.js';

const stopTelemetry = startTelemetry();
let runtime: Awaited<ReturnType<typeof start>>;
try {
  runtime = await start({ agents: [Bars, SupportRequestFinalizer], db, providers: [provider] });
} catch (error) {
  await stopTelemetry();
  throw error;
}
const port = Number(process.env.PORT || 3000);
const server = serve({ fetch: app.fetch, port, hostname: '0.0.0.0' }, () => {
  console.log(`Flue listening on port ${port}`);
});
const scanner = setInterval(() => void worker.scan(), 500);
void worker.scan();

async function shutdown(): Promise<void> {
  clearInterval(scanner);
  try {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => error ? reject(error) : resolve());
    });
    await runtime.stop();
  } catch (error) {
    console.error('Flue shutdown failed', error instanceof Error ? error.name : 'Error');
    process.exitCode = 1;
  } finally {
    await stopTelemetry().catch((error: unknown) => {
      console.warn('Telemetry shutdown failed', error instanceof Error ? error.name : 'Error');
    });
  }
}
process.once('SIGINT', () => void shutdown());
process.once('SIGTERM', () => void shutdown());
