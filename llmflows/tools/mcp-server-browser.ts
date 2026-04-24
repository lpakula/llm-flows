/**
 * MCP server: browser automation via stdio.
 *
 * Each agent run gets its own instance of this server (spawned by mcp-bridge).
 * The browser itself persists across runs via CDP — Chrome is launched as a
 * detached process and reconnected on subsequent starts.
 *
 * Environment variables:
 *   BROWSER_HEADLESS        – "true" (default) or "false"
 *   BROWSER_USER_DATA_DIR   – persistent profile directory
 *   BROWSER_ARTIFACTS_DIR   – base directory for screenshots
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { chromium, type Browser, type BrowserContext, type Page, type Locator } from "playwright";
import { existsSync, mkdirSync } from "fs";
import { join, basename } from "path";
import { spawn } from "child_process";

// ── Config ───────────────────────────────────────────────────────────

const headless = process.env.BROWSER_HEADLESS !== "false";
const userDataDir = process.env.BROWSER_USER_DATA_DIR || "";
const baseArtifactsDir = process.env.BROWSER_ARTIFACTS_DIR || "/tmp/browser-artifacts";

const CDP_PORT = 9222;
const CDP_URL = `http://localhost:${CDP_PORT}`;

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

// ── Session management ───────────────────────────────────────────────

interface Session {
  context: BrowserContext;
  page: Page;
  refMap: Map<number, Locator>;
  nextRef: number;
}

let browser: Browser | null = null;
let currentSession: Session | null = null;

const LAUNCH_ARGS = [
  "--no-first-run",
  "--disable-gpu",
  "--disable-infobars",
];

async function connectCDP(): Promise<Browser> {
  return await chromium.connectOverCDP(CDP_URL);
}

function launchChromeDetached(): void {
  const execPath = resolveChromePath();
  const args = [
    `--remote-debugging-port=${CDP_PORT}`,
    ...LAUNCH_ARGS,
    ...(headless ? ["--headless=new"] : []),
  ];
  if (userDataDir) {
    args.push(`--user-data-dir=${userDataDir}`);
  }
  const child = spawn(execPath, args, {
    detached: true,
    stdio: "ignore",
  });
  child.unref();
}

async function ensureBrowser(): Promise<Browser> {
  if (browser && browser.isConnected()) return browser;

  try {
    browser = await connectCDP();
    return browser;
  } catch { /* not running */ }

  launchChromeDetached();

  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      browser = await connectCDP();
      return browser;
    } catch { /* not ready */ }
  }
  throw new Error(`Chrome did not start on port ${CDP_PORT}`);
}

let sessionPromise: Promise<Session> | null = null;

async function getSession(): Promise<Session> {
  if (currentSession) {
    try {
      if (!currentSession.page.isClosed()) return currentSession;
    } catch { /* disconnected */ }
    currentSession = null;
  }
  if (sessionPromise) return sessionPromise;
  sessionPromise = _initSession();
  try { return await sessionPromise; }
  finally { sessionPromise = null; }
}

async function _initSession(): Promise<Session> {
  const b = await ensureBrowser();
  const contexts = b.contexts();
  const context = contexts[0] || await b.newContext();
  const pages = context.pages();
  const page = pages.length > 0 ? pages[pages.length - 1] : await context.newPage();

  mkdirSync(baseArtifactsDir, { recursive: true });
  try {
    const client = await context.newCDPSession(page);
    await client.send("Page.setDownloadBehavior", {
      behavior: "allow",
      downloadPath: baseArtifactsDir,
    });
  } catch { /* CDP session may fail on reconnect, non-critical */ }

  currentSession = { context, page, refMap: new Map(), nextRef: 1 };
  return currentSession;
}

// ── Aria snapshot with refs ──────────────────────────────────────────

const INTERACTIVE_ROLES = new Set([
  "link", "button", "textbox", "checkbox", "radio", "combobox",
  "menuitem", "tab", "searchbox", "slider", "spinbutton", "switch",
  "option", "menuitemcheckbox", "menuitemradio", "treeitem",
]);

const ARIA_LINE_RE = /^(\s*-\s+)(\w+)\s+"([^"]*)"(.*)$/;

async function takeSnapshot(session: Session): Promise<string> {
  const p = session.page;
  session.refMap.clear();
  session.nextRef = 1;

  try {
    const snapshot = await p.locator("body").ariaSnapshot();
    if (!snapshot || !snapshot.trim()) {
      return `Page: ${p.url()}\n(empty page)`;
    }

    const seen = new Map<string, number>();
    const lines = snapshot.split("\n");
    const result: string[] = [`Page: ${p.url()}`, ""];

    for (const line of lines) {
      const m = line.match(ARIA_LINE_RE);
      if (m) {
        const [, , role, name] = m;
        if (INTERACTIVE_ROLES.has(role)) {
          const ref = session.nextRef++;
          const key = `${role}:${name}`;
          const idx = seen.get(key) || 0;
          seen.set(key, idx + 1);
          const locator = p.getByRole(role as any, { name, exact: false }).nth(idx);
          session.refMap.set(ref, locator);
          result.push(`${line} [ref=${ref}]`);
          continue;
        }
      }
      result.push(line);
    }
    return result.join("\n");
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return `Page: ${p.url()}\n(accessibility snapshot error: ${msg})`;
  }
}

function resolveRef(session: Session, ref: number): Locator {
  const loc = session.refMap.get(ref);
  if (!loc) {
    throw new Error(`ref=${ref} not found. Run browser_snapshot first to get current refs.`);
  }
  return loc;
}

// ── MCP Server ───────────────────────────────────────────────────────

const server = new Server(
  { name: "llmflows-browser", version: "1.0.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "browser_navigate",
      description: "Navigate to a URL in the browser. Returns the page snapshot with interactive element refs.",
      inputSchema: {
        type: "object" as const,
        properties: {
          url: { type: "string", description: "URL to navigate to" },
        },
        required: ["url"],
      },
    },
    {
      name: "browser_snapshot",
      description: "Get the current page structure as a text snapshot. Interactive elements are tagged with [ref=N]. Use these ref numbers with browser_click and browser_fill.",
      inputSchema: { type: "object" as const, properties: {} },
    },
    {
      name: "browser_click",
      description: "Click an element by its ref number from the latest browser_snapshot. After clicking, returns a fresh snapshot.",
      inputSchema: {
        type: "object" as const,
        properties: {
          ref: { type: "number", description: "Element ref number from browser_snapshot" },
        },
        required: ["ref"],
      },
    },
    {
      name: "browser_fill",
      description: "Fill an input or textarea by its ref number. Clears existing content first. After filling, returns a fresh snapshot.",
      inputSchema: {
        type: "object" as const,
        properties: {
          ref: { type: "number", description: "Element ref number from browser_snapshot" },
          value: { type: "string", description: "Text to type into the field" },
        },
        required: ["ref", "value"],
      },
    },
    {
      name: "browser_screenshot",
      description: "Take a screenshot of the current page and save it to the artifacts directory. Returns the file path.",
      inputSchema: {
        type: "object" as const,
        properties: {
          filename: { type: "string", description: "Filename for the screenshot (default: screenshot.png)" },
        },
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "browser_navigate": {
        const session = await getSession();
        await session.page.goto((args as any).url, { waitUntil: "domcontentloaded", timeout: 30_000 });
        await session.page.waitForTimeout(1000);
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: snap }] };
      }
      case "browser_snapshot": {
        const session = await getSession();
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: snap }] };
      }
      case "browser_click": {
        const session = await getSession();
        const loc = resolveRef(session, (args as any).ref);
        await loc.first().click({ timeout: 10_000 });
        await session.page.waitForTimeout(1000);
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: `Clicked ref=${(args as any).ref}.\n\n${snap}` }] };
      }
      case "browser_fill": {
        const session = await getSession();
        const loc = resolveRef(session, (args as any).ref);
        await loc.first().fill((args as any).value, { timeout: 10_000 });
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: `Filled ref=${(args as any).ref} with "${(args as any).value}".\n\n${snap}` }] };
      }
      case "browser_screenshot": {
        const session = await getSession();
        const fname = basename((args as any).filename || "screenshot.png");
        mkdirSync(baseArtifactsDir, { recursive: true });
        const filePath = join(baseArtifactsDir, fname);
        await session.page.screenshot({ path: filePath, fullPage: false });
        return { content: [{ type: "text", text: `Screenshot saved to ${filePath}` }] };
      }
      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return { content: [{ type: "text", text: `Error in ${name}: ${msg}` }], isError: true };
  }
});

// ── stdio transport ──────────────────────────────────────────────────

const shutdown = () => {
  if (browser) {
    try { browser.disconnect(); } catch { /* ignore */ }
  }
  process.exit(0);
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

(async () => {
  const transport = new StdioServerTransport();
  await server.connect(transport);
})();
