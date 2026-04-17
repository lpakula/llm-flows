/**
 * Browser server: launches a Playwright browser and keeps it alive.
 *
 * The daemon spawns this as a detached subprocess.  It prints a
 * machine-readable WS_ENDPOINT line to stdout so the daemon can
 * capture the WebSocket URL, then stays alive until the process is
 * killed (SIGTERM / SIGINT).
 *
 * Environment variables:
 *   BROWSER_HEADLESS  – "true" (default) or "false"
 */

import { chromium } from "playwright";

const headless = process.env.BROWSER_HEADLESS !== "false";

async function main() {
  const server = await chromium.launchServer({
    headless,
    args: ["--no-first-run", "--disable-gpu"],
  });

  const ws = server.wsEndpoint();
  process.stdout.write(`WS_ENDPOINT:${ws}\n`);

  const shutdown = async () => {
    await server.close();
    process.exit(0);
  };

  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  process.stderr.write(`browser-server error: ${err}\n`);
  process.exit(1);
});
