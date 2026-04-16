/**
 * Pi extension: web_search + web_fetch tools.
 *
 * Providers:
 *   - DuckDuckGo (default, no API key)
 *   - Brave Search (requires BRAVE_API_KEY)
 *
 * The active provider and API key are passed via environment variables
 * set by the llmflows daemon:
 *   LLMFLOWS_WEB_SEARCH_PROVIDER  – "duckduckgo" | "brave"
 *   BRAVE_API_KEY                 – required when provider is "brave"
 */

import { Type } from "@sinclair/typebox";

const PROVIDER = (process.env.LLMFLOWS_WEB_SEARCH_PROVIDER || "duckduckgo").toLowerCase();
const BRAVE_API_KEY = process.env.BRAVE_API_KEY || "";

// ── Concurrency limiter to avoid rate-limit bans ──────────────────────

const MAX_CONCURRENT = 2;
let running = 0;
const queue: (() => void)[] = [];

function acquireSlot(): Promise<void> {
  if (running < MAX_CONCURRENT) {
    running++;
    return Promise.resolve();
  }
  return new Promise((resolve) => queue.push(() => { running++; resolve(); }));
}

function releaseSlot() {
  running--;
  const next = queue.shift();
  if (next) next();
}

async function withThrottle<T>(fn: () => Promise<T>): Promise<T> {
  await acquireSlot();
  try { return await fn(); } finally { releaseSlot(); }
}

async function fetchWithRetry(url: string, init: RequestInit, retries = 2): Promise<Response> {
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url, { ...init, signal: AbortSignal.timeout(10_000) });
      if (res.ok || res.status < 500) return res;
    } catch (e) {
      if (i === retries) throw e;
    }
    await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
  }
  throw new Error("fetch failed after retries");
}

// ── DuckDuckGo (HTML lite) ────────────────────────────────────────────

async function searchDuckDuckGo(query: string, count: number): Promise<string> {
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
  const res = await fetchWithRetry(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    },
  });
  const html = await res.text();

  const results: { title: string; url: string; snippet: string }[] = [];
  const linkRe =
    /<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi;
  const snippetRe =
    /<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/gi;

  const links = [...html.matchAll(linkRe)];
  const snippets = [...html.matchAll(snippetRe)];

  for (let i = 0; i < Math.min(links.length, count); i++) {
    const rawUrl = links[i][1];
    const title = links[i][2].replace(/<[^>]+>/g, "").trim();
    const snippet = (snippets[i]?.[1] || "")
      .replace(/<[^>]+>/g, "")
      .trim();

    let href = rawUrl;
    try {
      const parsed = new URL(rawUrl);
      const uddg = parsed.searchParams.get("uddg");
      if (uddg) href = decodeURIComponent(uddg);
    } catch {
      // keep rawUrl
    }

    results.push({ title, url: href, snippet });
  }

  if (results.length === 0) return "No results found.";
  return results
    .map((r, i) => `${i + 1}. **${r.title}**\n   ${r.url}\n   ${r.snippet}`)
    .join("\n\n");
}

// ── Brave Search ──────────────────────────────────────────────────────

async function searchBrave(query: string, count: number): Promise<string> {
  if (!BRAVE_API_KEY) return "Error: BRAVE_API_KEY is not configured.";

  const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${count}`;
  const res = await fetchWithRetry(url, {
    headers: {
      Accept: "application/json",
      "Accept-Encoding": "gzip",
      "X-Subscription-Token": BRAVE_API_KEY,
    },
  });

  if (!res.ok) return `Brave Search error: ${res.status} ${res.statusText}`;
  const data = (await res.json()) as {
    web?: {
      results?: { title: string; url: string; description: string }[];
    };
  };

  const results = data.web?.results || [];
  if (results.length === 0) return "No results found.";
  return results
    .map(
      (r: { title: string; url: string; description: string }, i: number) =>
        `${i + 1}. **${r.title}**\n   ${r.url}\n   ${r.description}`,
    )
    .join("\n\n");
}

// ── web_fetch ─────────────────────────────────────────────────────────

async function fetchUrl(
  url: string,
  maxChars: number,
): Promise<string> {
  const blockedPatterns = [
    /^https?:\/\/(localhost|127\.\d|10\.\d|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i,
  ];
  if (blockedPatterns.some((p) => p.test(url))) {
    return "Error: fetching private/local network URLs is not allowed.";
  }

  // Try Jina Reader first for cleaner extraction
  const jinaUrl = `https://r.jina.ai/${url}`;
  try {
    const res = await fetch(jinaUrl, {
      headers: { Accept: "text/plain" },
      signal: AbortSignal.timeout(15_000),
    });
    if (res.ok) {
      const text = await res.text();
      if (text.length > maxChars)
        return text.slice(0, maxChars) + "\n\n[... truncated]";
      return text;
    }
  } catch {
    // fall through to direct fetch
  }

  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (compatible; llmflows/1.0; +https://github.com/llmflows)",
      },
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) return `Error: HTTP ${res.status} ${res.statusText}`;
    const html = await res.text();
    const text = html
      .replace(/<script[\s\S]*?<\/script>/gi, "")
      .replace(/<style[\s\S]*?<\/style>/gi, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (text.length > maxChars)
      return text.slice(0, maxChars) + "\n\n[... truncated]";
    return text;
  } catch (e: unknown) {
    return `Error fetching URL: ${e instanceof Error ? e.message : String(e)}`;
  }
}

// ── Extension entry point ─────────────────────────────────────────────

export default function activate(api: any) {
  api.registerTool({
    name: "web_search",
    label: "Web Search",
    description:
      "Search the web for information. Returns a list of results with titles, URLs, and snippets.",
    promptSnippet:
      "web_search: Search the web. Params: query (string, required), count (number, 1-10, default 5).",
    parameters: Type.Object({
      query: Type.String({ description: "Search query" }),
      count: Type.Optional(
        Type.Number({
          description: "Number of results (1-10)",
          minimum: 1,
          maximum: 10,
          default: 5,
        }),
      ),
    }),
    async execute(
      _toolCallId: string,
      params: { query: string; count?: number },
    ) {
      const count = Math.min(Math.max(params.count ?? 5, 1), 10);
      const text = await withThrottle(async () => {
        if (PROVIDER === "brave") {
          return searchBrave(params.query, count);
        }
        return searchDuckDuckGo(params.query, count);
      });
      return { content: [{ type: "text", text }] };
    },
  });

  api.registerTool({
    name: "web_fetch",
    label: "Web Fetch",
    description:
      "Fetch a URL and return its content as readable text. Useful for reading articles, documentation, or any web page.",
    promptSnippet:
      "web_fetch: Fetch a URL and return readable text. Params: url (string, required), max_chars (number, default 20000).",
    parameters: Type.Object({
      url: Type.String({ description: "URL to fetch" }),
      max_chars: Type.Optional(
        Type.Number({
          description: "Maximum characters to return",
          default: 20000,
        }),
      ),
    }),
    async execute(
      _toolCallId: string,
      params: { url: string; max_chars?: number },
    ) {
      const maxChars = params.max_chars ?? 20000;
      const text = await withThrottle(() => fetchUrl(params.url, maxChars));
      return { content: [{ type: "text", text }] };
    },
  });
}
