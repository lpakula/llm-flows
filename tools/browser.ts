/**
 * Pi extension: browser automation tools.
 *
 * Connects to a running Playwright browser server (started by the daemon)
 * via a WebSocket endpoint.  Provides tools for navigating, clicking,
 * filling forms, taking screenshots, and reading page structure.
 *
 * Uses an accessibility-snapshot + numeric-ref model:
 *   - browser_snapshot returns a text representation with [ref=N] tags
 *   - browser_click / browser_fill target elements by ref number
 *
 * Environment variables (set by the daemon / PiExecutor):
 *   BROWSER_WS_ENDPOINT   – Playwright browser server WebSocket URL
 *   BROWSER_ARTIFACTS_DIR  – directory to save screenshots into
 */

import { Type } from "@sinclair/typebox";
import { chromium, type Browser, type Page, type Locator } from "playwright";
import { writeFileSync, mkdirSync } from "fs";
import { join } from "path";

const WS_ENDPOINT = process.env.BROWSER_WS_ENDPOINT || "";
const ARTIFACTS_DIR = process.env.BROWSER_ARTIFACTS_DIR || "/tmp";

// ── Shared state ──────────────────────────────────────────────────────

let browser: Browser | null = null;
let page: Page | null = null;
let refMap = new Map<number, Locator>();
let nextRef = 1;

async function ensurePage(): Promise<Page> {
  if (!WS_ENDPOINT) throw new Error("BROWSER_WS_ENDPOINT is not set.");
  if (!browser) {
    browser = await chromium.connect(WS_ENDPOINT);
  }
  if (!page || page.isClosed()) {
    const contexts = browser.contexts();
    if (contexts.length > 0 && contexts[0].pages().length > 0) {
      page = contexts[0].pages()[0];
    } else {
      const ctx = contexts.length > 0 ? contexts[0] : await browser.newContext();
      page = await ctx.newPage();
    }
  }
  return page;
}

// ── Accessibility snapshot with refs ──────────────────────────────────

interface SnapNode {
  role: string;
  name: string;
  value?: string;
  children?: SnapNode[];
}

function buildSnapshot(
  node: SnapNode,
  depth: number,
  lines: string[],
  pageObj: Page,
): void {
  const indent = "  ".repeat(depth);
  const role = node.role;
  const name = node.name || "";

  const interactiveRoles = new Set([
    "link",
    "button",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "menuitem",
    "tab",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "option",
    "menuitemcheckbox",
    "menuitemradio",
    "treeitem",
  ]);

  if (interactiveRoles.has(role)) {
    const ref = nextRef++;
    const locator = pageObj.getByRole(role as any, { name, exact: false });
    refMap.set(ref, locator);
    const valueStr = node.value ? ` value="${node.value}"` : "";
    lines.push(`${indent}${role} "${name}"${valueStr} [ref=${ref}]`);
  } else if (role === "text" || role === "StaticText") {
    if (name.trim()) {
      lines.push(`${indent}${name}`);
    }
  } else if (role === "heading") {
    lines.push(`${indent}heading "${name}"`);
  } else if (role === "img" || role === "image") {
    lines.push(`${indent}image "${name}"`);
  }

  if (node.children) {
    for (const child of node.children) {
      buildSnapshot(child, depth + 1, lines, pageObj);
    }
  }
}

async function takeSnapshot(): Promise<string> {
  const p = await ensurePage();
  refMap.clear();
  nextRef = 1;

  let tree: SnapNode | null = null;
  try {
    tree = (await p.accessibility.snapshot()) as SnapNode | null;
  } catch {
    return `Page: ${p.url()}\n(accessibility snapshot unavailable)`;
  }

  if (!tree) {
    return `Page: ${p.url()}\n(empty page)`;
  }

  const lines: string[] = [`Page: ${p.url()}`, ""];
  buildSnapshot(tree, 0, lines, p);
  return lines.join("\n");
}

function resolveRef(ref: number): Locator {
  const loc = refMap.get(ref);
  if (!loc) {
    throw new Error(
      `ref=${ref} not found. Run browser_snapshot first to get current refs.`,
    );
  }
  return loc;
}

// ── Extension entry point ─────────────────────────────────────────────

export default function activate(api: any) {
  api.registerTool({
    name: "browser_navigate",
    label: "Browser Navigate",
    description:
      "Navigate to a URL in the browser. Returns the page snapshot with interactive element refs.",
    promptSnippet:
      'browser_navigate: Open a URL. Params: url (string). Returns page snapshot with [ref=N] for interactive elements.',
    parameters: Type.Object({
      url: Type.String({ description: "URL to navigate to" }),
    }),
    async execute(_id: string, params: { url: string }) {
      try {
        const p = await ensurePage();
        await p.goto(params.url, { waitUntil: "domcontentloaded", timeout: 30_000 });
        await p.waitForTimeout(1000);
        const snap = await takeSnapshot();
        return { content: [{ type: "text", text: snap }] };
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return { content: [{ type: "text", text: `Error navigating: ${msg}` }] };
      }
    },
  });

  api.registerTool({
    name: "browser_snapshot",
    label: "Browser Snapshot",
    description:
      "Get the current page structure as a text snapshot. " +
      "Interactive elements are tagged with [ref=N]. " +
      "Use these ref numbers with browser_click and browser_fill.",
    promptSnippet:
      "browser_snapshot: Get page structure with [ref=N] tags. No params.",
    parameters: Type.Object({}),
    async execute() {
      try {
        const snap = await takeSnapshot();
        return { content: [{ type: "text", text: snap }] };
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return { content: [{ type: "text", text: `Error: ${msg}` }] };
      }
    },
  });

  api.registerTool({
    name: "browser_click",
    label: "Browser Click",
    description:
      "Click an element by its ref number from the latest browser_snapshot. " +
      "After clicking, returns a fresh snapshot of the page.",
    promptSnippet:
      "browser_click: Click element by ref number. Params: ref (number).",
    parameters: Type.Object({
      ref: Type.Number({ description: "Element ref number from browser_snapshot" }),
    }),
    async execute(_id: string, params: { ref: number }) {
      try {
        const loc = resolveRef(params.ref);
        await loc.first().click({ timeout: 10_000 });
        await (await ensurePage()).waitForTimeout(1000);
        const snap = await takeSnapshot();
        return { content: [{ type: "text", text: `Clicked ref=${params.ref}.\n\n${snap}` }] };
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return { content: [{ type: "text", text: `Error clicking ref=${params.ref}: ${msg}` }] };
      }
    },
  });

  api.registerTool({
    name: "browser_fill",
    label: "Browser Fill",
    description:
      "Fill an input or textarea by its ref number. Clears existing content first. " +
      "After filling, returns a fresh snapshot.",
    promptSnippet:
      'browser_fill: Type into an input. Params: ref (number), value (string).',
    parameters: Type.Object({
      ref: Type.Number({ description: "Element ref number from browser_snapshot" }),
      value: Type.String({ description: "Text to type into the field" }),
    }),
    async execute(_id: string, params: { ref: number; value: string }) {
      try {
        const loc = resolveRef(params.ref);
        await loc.first().fill(params.value, { timeout: 10_000 });
        const snap = await takeSnapshot();
        return {
          content: [
            { type: "text", text: `Filled ref=${params.ref} with "${params.value}".\n\n${snap}` },
          ],
        };
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return { content: [{ type: "text", text: `Error filling ref=${params.ref}: ${msg}` }] };
      }
    },
  });

  api.registerTool({
    name: "browser_screenshot",
    label: "Browser Screenshot",
    description:
      "Take a screenshot of the current page and save it to the artifacts directory. " +
      "Returns the file path of the saved screenshot.",
    promptSnippet:
      "browser_screenshot: Capture page screenshot. Params: filename (string, optional, default 'screenshot.png').",
    parameters: Type.Object({
      filename: Type.Optional(
        Type.String({
          description: "Filename for the screenshot (default: screenshot.png)",
          default: "screenshot.png",
        }),
      ),
    }),
    async execute(_id: string, params: { filename?: string }) {
      try {
        const p = await ensurePage();
        const fname = params.filename || "screenshot.png";
        mkdirSync(ARTIFACTS_DIR, { recursive: true });
        const filePath = join(ARTIFACTS_DIR, fname);
        await p.screenshot({ path: filePath, fullPage: false });
        return {
          content: [{ type: "text", text: `Screenshot saved to ${filePath}` }],
        };
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return { content: [{ type: "text", text: `Error taking screenshot: ${msg}` }] };
      }
    },
  });
}
