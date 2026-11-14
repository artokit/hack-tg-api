import { start } from '@flue/runtime/node';
import { serve } from '@hono/node-server';

import app, { worker } from './app.js';
import { Bars } from './agents/bars.js';
import db from './db.js';
import { provider } from './provider.js';

const runtime = await start({ agents: [Bars], db, providers: [provider] });
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
  }
}
process.once('SIGINT', () => void shutdown());
process.once('SIGTERM', () => void shutdown());
