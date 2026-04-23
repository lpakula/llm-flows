/**
 * MCP server: browser automation via SSE.
 *
 * Runs a single Chrome instance and provides session-isolated browser
 * contexts keyed by _session_id (= run_id).  Multiple concurrent runs
 * each get their own isolated context with separate cookies/storage.
 *
 * Session continuity:
 *   - Within a run: same session_id → same BrowserContext, pages persist
 *   - Across runs: contexts load storageState from the user_data_dir profile
 *   - On release: context is closed, storage state saved back to profile
 *
 * Usage:
 *   tsx mcp-server-browser.ts --port 19101
 *
 * Environment variables:
 *   BROWSER_HEADLESS        – "true" (default) or "false"
 *   BROWSER_USER_DATA_DIR   – persistent profile directory
 *   BROWSER_ARTIFACTS_DIR   – base directory for screenshots
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { chromium, type Browser, type BrowserContext, type Page, type Locator } from "playwright";
import { existsSync, mkdirSync, writeFileSync } from "fs";
import { join, basename } from "path";
import * as http from "http";

// ── Config ───────────────────────────────────────────────────────────

const PORT = parseInt(process.argv.find((_, i, a) => a[i - 1] === "--port") || "19101", 10);
const headless = process.env.BROWSER_HEADLESS !== "false";
const userDataDir = process.env.BROWSER_USER_DATA_DIR || "";
const baseArtifactsDir = process.env.BROWSER_ARTIFACTS_DIR || "/tmp/browser-artifacts";

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
  lastAccess: number;
}

let browser: Browser | null = null;
let persistentContext: BrowserContext | null = null;
const sessions = new Map<string, Session>();
const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes

const LAUNCH_ARGS = [
  "--no-first-run",
  "--disable-gpu",
  "--disable-infobars",
  "--disable-blink-features=AutomationControlled",
];
const IGNORE_DEFAULT_ARGS = ["--enable-automation"];

async function ensureBrowser(): Promise<Browser> {
  if (browser && browser.isConnected()) return browser;

  const execPath = resolveChromePath();
  browser = await chromium.launch({
    executablePath: execPath,
    headless,
    args: LAUNCH_ARGS,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
  });
  return browser;
}

async function ensurePersistentContext(): Promise<BrowserContext> {
  if (persistentContext) return persistentContext;

  const execPath = resolveChromePath();
  persistentContext = await chromium.launchPersistentContext(userDataDir, {
    executablePath: execPath,
    headless,
    args: LAUNCH_ARGS,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
  });
  await persistentContext.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => undefined });
  });
  return persistentContext;
}

async function setupContext(ctx: BrowserContext) {
  await ctx.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => undefined });
  });
}

async function getSession(sessionId: string): Promise<Session> {
  const existing = sessions.get(sessionId);
  if (existing) {
    existing.lastAccess = Date.now();
    if (!existing.page.isClosed()) return existing;
    sessions.delete(sessionId);
  }

  let context: BrowserContext;
  if (userDataDir) {
    context = await ensurePersistentContext();
  } else {
    const b = await ensureBrowser();
    context = await b.newContext();
    await setupContext(context);
  }
  const page = await context.newPage();

  const artifactsDir = join(baseArtifactsDir, sessionId);
  mkdirSync(artifactsDir, { recursive: true });
  const client = await context.newCDPSession(page);
  await client.send("Page.setDownloadBehavior", {
    behavior: "allow",
    downloadPath: artifactsDir,
  });

  const session: Session = {
    context,
    page,
    refMap: new Map(),
    nextRef: 1,
    lastAccess: Date.now(),
  };
  sessions.set(sessionId, session);
  return session;
}

async function releaseSession(sessionId: string): Promise<void> {
  const session = sessions.get(sessionId);
  if (!session) return;
  try {
    if (userDataDir) {
      await session.page.close();
    } else {
      await session.context.close();
    }
  } catch { /* ignore */ }
  sessions.delete(sessionId);
}

// Periodic idle cleanup
setInterval(() => {
  const now = Date.now();
  for (const [id, session] of sessions) {
    if (now - session.lastAccess > IDLE_TIMEOUT_MS) {
      console.error(`[browser] Closing idle session ${id}`);
      releaseSession(id);
    }
  }
}, 60_000);

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
    {
      name: "browser_release_session",
      description: "Close the browser context for a session, freeing resources. Called by the daemon, not by agents.",
      inputSchema: {
        type: "object" as const,
        properties: {
          session_id: { type: "string", description: "Session ID to release" },
        },
        required: ["session_id"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const sessionId = (args as any)?._session_id || "default";

  try {
    switch (name) {
      case "browser_navigate": {
        const session = await getSession(sessionId);
        await session.page.goto((args as any).url, { waitUntil: "domcontentloaded", timeout: 30_000 });
        await session.page.waitForTimeout(1000);
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: snap }] };
      }
      case "browser_snapshot": {
        const session = await getSession(sessionId);
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: snap }] };
      }
      case "browser_click": {
        const session = await getSession(sessionId);
        const loc = resolveRef(session, (args as any).ref);
        await loc.first().click({ timeout: 10_000 });
        await session.page.waitForTimeout(1000);
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: `Clicked ref=${(args as any).ref}.\n\n${snap}` }] };
      }
      case "browser_fill": {
        const session = await getSession(sessionId);
        const loc = resolveRef(session, (args as any).ref);
        await loc.first().fill((args as any).value, { timeout: 10_000 });
        const snap = await takeSnapshot(session);
        return { content: [{ type: "text", text: `Filled ref=${(args as any).ref} with "${(args as any).value}".\n\n${snap}` }] };
      }
      case "browser_screenshot": {
        const session = await getSession(sessionId);
        const fname = basename((args as any).filename || "screenshot.png");
        const artifactsDir = join(baseArtifactsDir, sessionId);
        mkdirSync(artifactsDir, { recursive: true });
        const filePath = join(artifactsDir, fname);
        await session.page.screenshot({ path: filePath, fullPage: false });
        return { content: [{ type: "text", text: `Screenshot saved to ${filePath}` }] };
      }
      case "browser_release_session": {
        const sid = (args as any).session_id || sessionId;
        await releaseSession(sid);
        return { content: [{ type: "text", text: `Session ${sid} released.` }] };
      }
      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return { content: [{ type: "text", text: `Error in ${name}: ${msg}` }], isError: true };
  }
});

// ── HTTP / SSE transport ─────────────────────────────────────────────

const transports = new Map<string, SSEServerTransport>();

const httpServer = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://localhost:${PORT}`);

  if (url.pathname === "/sse" && req.method === "GET") {
    const transport = new SSEServerTransport("/messages", res);
    const id = Math.random().toString(36).slice(2);
    transports.set(id, transport);
    res.on("close", () => transports.delete(id));
    await server.connect(transport);
    return;
  }

  if (url.pathname === "/messages" && req.method === "POST") {
    let body = "";
    req.on("data", (chunk: Buffer) => { body += chunk.toString(); });
    req.on("end", async () => {
      for (const transport of transports.values()) {
        try {
          await transport.handlePostMessage(req, res, body);
          return;
        } catch { /* try next */ }
      }
      res.writeHead(400);
      res.end("No matching transport");
    });
    return;
  }

  // Session release endpoint (called by McpService.release_session)
  if (url.pathname.startsWith("/session/") && req.method === "DELETE") {
    const sid = url.pathname.split("/session/")[1];
    if (sid) await releaseSession(sid);
    res.writeHead(200);
    res.end("ok");
    return;
  }

  res.writeHead(404);
  res.end("Not found");
});

httpServer.listen(PORT, () => {
  console.error(`[browser] MCP server listening on http://localhost:${PORT}`);
});

const shutdown = async () => {
  for (const [id] of sessions) {
    await releaseSession(id);
  }
  if (persistentContext) {
    try { await persistentContext.close(); } catch { /* ignore */ }
  }
  if (browser) {
    try { await browser.close(); } catch { /* ignore */ }
  }
  httpServer.close();
  process.exit(0);
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
