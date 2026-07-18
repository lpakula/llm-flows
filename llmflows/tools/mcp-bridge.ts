/**
 * Pi extension: MCP bridge — the single extension that connects Pi to all MCP servers.
 *
 * Reads MCP_SERVERS (JSON array of {server_id, command, args?, env?}) from env.
 * For each server, spawns a subprocess via stdio transport, discovers tools via
 * listTools(), and registers them as Pi tools.  Tool calls are forwarded to the
 * correct MCP server.  Subprocesses are cleaned up when the bridge exits.
 *
 * If an MCP server process dies between tool calls, the bridge reconnects once
 * and retries the call (common with long-lived npx-backed servers in Docker).
 */

import { Type, type TSchema } from "@sinclair/typebox";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

interface ServerEntry {
  server_id: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

interface LiveServer {
  entry: ServerEntry;
  client: Client;
  transport: StdioClientTransport;
}

const MCP_SERVERS: ServerEntry[] = JSON.parse(process.env.MCP_SERVERS || "[]");

function jsonSchemaToTypebox(schema: any): TSchema {
  if (!schema || typeof schema !== "object") return Type.Any();

  if (schema.type === "string") {
    const opts: any = {};
    if (schema.description) opts.description = schema.description;
    if (schema.enum) return Type.Union(schema.enum.map((v: string) => Type.Literal(v)), opts);
    return Type.String(opts);
  }
  if (schema.type === "number" || schema.type === "integer") {
    const opts: any = {};
    if (schema.description) opts.description = schema.description;
    if (schema.minimum !== undefined) opts.minimum = schema.minimum;
    if (schema.maximum !== undefined) opts.maximum = schema.maximum;
    return schema.type === "integer" ? Type.Integer(opts) : Type.Number(opts);
  }
  if (schema.type === "boolean") {
    return Type.Boolean({ description: schema.description });
  }
  if (schema.type === "array") {
    return Type.Array(jsonSchemaToTypebox(schema.items || {}), {
      description: schema.description,
    });
  }
  if (schema.type === "object" || schema.properties) {
    const props: Record<string, TSchema> = {};
    const required = new Set(schema.required || []);
    for (const [key, val] of Object.entries(schema.properties || {})) {
      const converted = jsonSchemaToTypebox(val);
      props[key] = required.has(key) ? converted : Type.Optional(converted);
    }
    return Type.Object(props, { description: schema.description });
  }
  return Type.Any();
}

function serverEnv(entry: ServerEntry): Record<string, string> {
  return {
    PATH: process.env.PATH || "",
    HOME: process.env.HOME || "",
    NODE_PATH: process.env.NODE_PATH || "",
    TMPDIR: process.env.TMPDIR || "/tmp",
    ...(process.env.LLMFLOWS_RUNNER
      ? { LLMFLOWS_RUNNER: process.env.LLMFLOWS_RUNNER }
      : {}),
    ...entry.env,
  };
}

async function connectServer(entry: ServerEntry): Promise<LiveServer> {
  const transport = new StdioClientTransport({
    command: entry.command,
    args: entry.args || [],
    env: serverEnv(entry),
    stderr: "inherit",
  });
  transport.onclose = () => {
    console.error(`[mcp-bridge] Transport closed for ${entry.server_id}`);
  };
  transport.onerror = (err) => {
    console.error(`[mcp-bridge] Transport error for ${entry.server_id}:`, err);
  };

  const client = new Client(
    { name: `llmflows-bridge-${entry.server_id}`, version: "1.0.0" },
    { capabilities: {} },
  );
  await client.connect(transport);
  return { entry, client, transport };
}

function isDisconnectError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /not connected/i.test(msg);
}

const lives = new Map<string, LiveServer>();

process.on("exit", () => {
  for (const live of lives.values()) {
    try {
      live.transport.close();
    } catch {
      /* ignore */
    }
  }
});

async function callWithReconnect(
  serverId: string,
  toolName: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  let live = lives.get(serverId);
  if (!live) {
    throw new Error(`MCP server '${serverId}' is not connected`);
  }

  try {
    return await live.client.callTool({ name: toolName, arguments: params });
  } catch (err) {
    if (!isDisconnectError(err)) throw err;

    console.error(
      `[mcp-bridge] ${serverId} disconnected during ${toolName}; reconnecting…`,
    );
    try {
      await live.transport.close();
    } catch {
      /* ignore */
    }

    live = await connectServer(live.entry);
    lives.set(serverId, live);
    // Refresh tool metadata cache on the new client.
    await live.client.listTools();
    return await live.client.callTool({ name: toolName, arguments: params });
  }
}

export default async function activate(api: any) {
  if (MCP_SERVERS.length === 0) return;

  for (const server of MCP_SERVERS) {
    let live: LiveServer;
    try {
      live = await connectServer(server);
      lives.set(server.server_id, live);
    } catch (err) {
      console.error(
        `[mcp-bridge] Failed to start ${server.server_id} (${server.command}):`,
        err,
      );
      continue;
    }

    let tools: any[];
    try {
      const result = await live.client.listTools();
      tools = result.tools || [];
    } catch (err) {
      console.error(`[mcp-bridge] Failed to list tools from ${server.server_id}:`, err);
      continue;
    }

    for (const tool of tools) {
      const toolName = tool.name;
      const parameters = tool.inputSchema
        ? jsonSchemaToTypebox(tool.inputSchema)
        : Type.Object({});
      const serverId = server.server_id;

      api.registerTool({
        name: toolName,
        label: tool.name,
        description: tool.description || `Tool from ${serverId}`,
        promptSnippet: tool.description || "",
        parameters,
        async execute(_toolCallId: string, params: Record<string, unknown>) {
          try {
            const result = await callWithReconnect(serverId, toolName, params);
            const content = (result as any).content;
            if (Array.isArray(content)) return { content };
            if (typeof content === "string") {
              return { content: [{ type: "text", text: content }] };
            }
            return {
              content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
            };
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            return { content: [{ type: "text", text: `Error: ${msg}` }] };
          }
        },
      });
    }

    console.error(
      `[mcp-bridge] Connected to ${server.server_id}: ${tools.length} tool(s) registered`,
    );
  }
}
