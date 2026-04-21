/**
 * Browser server: launches Chrome with CDP and keeps it alive.
 *
 * Uses --remote-debugging-port so each step's Pi extension can connect
 * via connectOverCDP().  Unlike Playwright's own server protocol, CDP
 * connections share browser state — pages, cookies, and contexts persist
 * across client reconnections.
 *
 * Prints a WS_ENDPOINT line to stdout with the CDP WebSocket URL.
 *
 * Environment variables:
 *   BROWSER_HEADLESS       – "true" (default) or "false"
 *   BROWSER_USER_DATA_DIR  – persistent profile directory (empty = temp profile)
 */

import { spawn, type ChildProcess } from "child_process";
import { existsSync } from "fs";

const headless = process.env.BROWSER_HEADLESS !== "false";
const userDataDir = process.env.BROWSER_USER_DATA_DIR || "";

const CHROME_PATHS = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
];

function resolveChromePath(): string {
  for (const p of CHROME_PATHS) {
    if (existsSync(p)) return p;
  }
  throw new Error(`Google Chrome not found. Searched: ${CHROME_PATHS.join(", ")}`);
}

async function main() {
  const execPath = resolveChromePath();

  const args = [
    "--no-first-run",
    "--disable-gpu",
    "--remote-debugging-port=0",
  ];
  if (headless) {
    args.push("--headless=new");
  }
  if (userDataDir) {
    args.push(`--user-data-dir=${userDataDir}`);
  }

  const proc: ChildProcess = spawn(execPath, args, {
    stdio: ["pipe", "pipe", "pipe"],
  });

  const cdpUrl = await new Promise<string>((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error("Chrome did not print CDP endpoint within 15s"));
    }, 15_000);

    proc.stderr?.on("data", (data: Buffer) => {
      const text = data.toString();
      const m = text.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (m) {
        clearTimeout(timeout);
        resolve(m[1]);
      }
    });

    proc.on("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`Chrome exited with code ${code}`));
    });
  });

  process.stdout.write(`WS_ENDPOINT:${cdpUrl}\n`);

  const shutdown = () => {
    proc.kill("SIGTERM");
    process.exit(0);
  };

  proc.on("exit", () => process.exit(0));
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  process.stderr.write(`browser-server error: ${err}\n`);
  process.exit(1);
});
