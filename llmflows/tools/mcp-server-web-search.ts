/**
 * MCP server: web search + fetch via SSE.
 *
 * Stateless — handles concurrent requests from multiple runs without
 * any session isolation needed.
 *
 * Usage:
 *   tsx mcp-server-web-search.ts --port 19100
 *
 * Environment variables:
 *   WEB_SEARCH_PROVIDER   – "duckduckgo" | "brave" | "perplexity" | "serpapi"
 *   BRAVE_API_KEY          – required when provider is "brave"
 *   PERPLEXITY_API_KEY     – required when provider is "perplexity"
 *   SERPAPI_API_KEY         – required when provider is "serpapi"
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import * as http from "http";

const PORT = parseInt(process.argv.find((_, i, a) => a[i - 1] === "--port") || "19100", 10);
const PROVIDER = (process.env.WEB_SEARCH_PROVIDER || process.env.LLMFLOWS_WEB_SEARCH_PROVIDER || "duckduckgo").toLowerCase();
const BRAVE_API_KEY = process.env.BRAVE_API_KEY || "";
const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY || "";
const SERPAPI_API_KEY = process.env.SERPAPI_API_KEY || "";

// ── Concurrency limiter ──────────────────────────────────────────────

const MAX_CONCURRENT = 4;
let running = 0;
const queue: (() => void)[] = [];

function acquireSlot(): Promise<void> {
  if (running < MAX_CONCURRENT) { running++; return Promise.resolve(); }
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

// ── Search providers ─────────────────────────────────────────────────

async function searchDuckDuckGo(query: string, count: number): Promise<string> {
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
  const res = await fetchWithRetry(url, {
    headers: {
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    },
  });
  const html = await res.text();
  const results: { title: string; url: string; snippet: string }[] = [];
  const linkRe = /<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi;
  const snippetRe = /<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/gi;
  const links = [...html.matchAll(linkRe)];
  const snippets = [...html.matchAll(snippetRe)];

  for (let i = 0; i < Math.min(links.length, count); i++) {
    const rawUrl = links[i][1];
    const title = links[i][2].replace(/<[^>]+>/g, "").trim();
    const snippet = (snippets[i]?.[1] || "").replace(/<[^>]+>/g, "").trim();
    let href = rawUrl;
    try {
      const parsed = new URL(rawUrl);
      const uddg = parsed.searchParams.get("uddg");
      if (uddg) href = decodeURIComponent(uddg);
    } catch { /* keep rawUrl */ }
    results.push({ title, url: href, snippet });
  }
  if (results.length === 0) return "No results found.";
  return results.map((r, i) => `${i + 1}. **${r.title}**\n   ${r.url}\n   ${r.snippet}`).join("\n\n");
}

async function searchBrave(query: string, count: number): Promise<string> {
  if (!BRAVE_API_KEY) return "Error: BRAVE_API_KEY is not configured.";
  const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${count}`;
  const res = await fetchWithRetry(url, {
    headers: { Accept: "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": BRAVE_API_KEY },
  });
  if (!res.ok) return `Brave Search error: ${res.status} ${res.statusText}`;
  const data = (await res.json()) as any;
  const results = data.web?.results || [];
  if (results.length === 0) return "No results found.";
  return results.map((r: any, i: number) => `${i + 1}. **${r.title}**\n   ${r.url}\n   ${r.description}`).join("\n\n");
}

async function searchPerplexity(query: string, count: number): Promise<string> {
  if (!PERPLEXITY_API_KEY) return "Error: PERPLEXITY_API_KEY is not configured.";
  const res = await fetchWithRetry("https://api.perplexity.ai/search", {
    method: "POST",
    headers: { Authorization: `Bearer ${PERPLEXITY_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ query, max_results: count }),
  });
  if (!res.ok) return `Perplexity Search error: ${res.status} ${res.statusText}`;
  const data = (await res.json()) as any;
  const results = data.results || [];
  if (results.length === 0) return "No results found.";
  return results.map((r: any, i: number) => `${i + 1}. **${r.title}**\n   ${r.url}\n   ${r.snippet}`).join("\n\n");
}

async function searchSerpApi(query: string, count: number): Promise<string> {
  if (!SERPAPI_API_KEY) return "Error: SERPAPI_API_KEY is not configured.";
  const params = new URLSearchParams({ q: query, api_key: SERPAPI_API_KEY, engine: "google", num: String(count) });
  const res = await fetchWithRetry(`https://serpapi.com/search.json?${params}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) return `SerpAPI error: ${res.status} ${res.statusText}`;
  const data = (await res.json()) as any;
  const results = data.organic_results || [];
  if (results.length === 0) return "No results found.";
  return results.slice(0, count).map((r: any, i: number) => `${i + 1}. **${r.title}**\n   ${r.link}\n   ${r.snippet}`).join("\n\n");
}

async function doSearch(query: string, count: number): Promise<string> {
  if (PROVIDER === "perplexity") return searchPerplexity(query, count);
  if (PROVIDER === "serpapi") return searchSerpApi(query, count);
  if (PROVIDER === "brave") return searchBrave(query, count);
  return searchDuckDuckGo(query, count);
}

async function fetchUrl(url: string, maxChars: number): Promise<string> {
  const blockedPatterns = [/^https?:\/\/(localhost|127\.\d|10\.\d|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i];
  if (blockedPatterns.some((p) => p.test(url))) {
    return "Error: fetching private/local network URLs is not allowed.";
  }
  const jinaUrl = `https://r.jina.ai/${url}`;
  try {
    const res = await fetch(jinaUrl, { headers: { Accept: "text/plain" }, signal: AbortSignal.timeout(15_000) });
    if (res.ok) {
      const text = await res.text();
      return text.length > maxChars ? text.slice(0, maxChars) + "\n\n[... truncated]" : text;
    }
  } catch { /* fall through */ }
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; llmflows/1.0; +https://github.com/llmflows)" },
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) return `Error: HTTP ${res.status} ${res.statusText}`;
    const html = await res.text();
    const text = html.replace(/<script[\s\S]*?<\/script>/gi, "").replace(/<style[\s\S]*?<\/style>/gi, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    return text.length > maxChars ? text.slice(0, maxChars) + "\n\n[... truncated]" : text;
  } catch (e: unknown) {
    return `Error fetching URL: ${e instanceof Error ? e.message : String(e)}`;
  }
}

// ── MCP Server ───────────────────────────────────────────────────────

const server = new Server(
  { name: "llmflows-web-search", version: "1.0.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "web_search",
      description: "Search the web for information. Returns a list of results with titles, URLs, and snippets.",
      inputSchema: {
        type: "object" as const,
        properties: {
          query: { type: "string", description: "Search query" },
          count: { type: "number", description: "Number of results (1-10)", minimum: 1, maximum: 10 },
        },
        required: ["query"],
      },
    },
    {
      name: "web_fetch",
      description: "Fetch a URL and return its content as readable text. Useful for reading articles, documentation, or any web page.",
      inputSchema: {
        type: "object" as const,
        properties: {
          url: { type: "string", description: "URL to fetch" },
          max_chars: { type: "number", description: "Maximum characters to return (default: 20000)" },
        },
        required: ["url"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "web_search": {
        const query = (args as any).query;
        const count = Math.min(Math.max((args as any).count ?? 5, 1), 10);
        const text = await withThrottle(() => doSearch(query, count));
        return { content: [{ type: "text", text }] };
      }
      case "web_fetch": {
        const url = (args as any).url;
        const maxChars = (args as any).max_chars ?? 20000;
        const text = await withThrottle(() => fetchUrl(url, maxChars));
        return { content: [{ type: "text", text }] };
      }
      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
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

  res.writeHead(404);
  res.end("Not found");
});

httpServer.listen(PORT, () => {
  console.error(`[web-search] MCP server listening on http://localhost:${PORT}`);
});

process.on("SIGTERM", () => { httpServer.close(); process.exit(0); });
process.on("SIGINT", () => { httpServer.close(); process.exit(0); });
