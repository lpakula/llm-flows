/**
 * Pi extension: MCP bridge — the single extension that connects Pi to all MCP servers.
 *
 * Reads MCP_SERVERS (JSON array of {server_id, command, args?, env?}) from env.
 * For each server, spawns a subprocess via stdio transport, discovers tools via
 * listTools(), and registers them as Pi tools.  Tool calls are forwarded to the
 * correct MCP server.  Subprocesses are cleaned up when the bridge exits.
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

const transports: StdioClientTransport[] = [];

process.on("exit", () => {
  for (const t of transports) {
    try { t.close(); } catch { /* ignore */ }
  }
});

export default async function activate(api: any) {
  if (MCP_SERVERS.length === 0) return;

  for (const server of MCP_SERVERS) {
    let client: Client;
    try {
      const transport = new StdioClientTransport({
        command: server.command,
        args: server.args || [],
        env: { ...process.env, ...server.env },
      });
      transports.push(transport);
      client = new Client(
        { name: `llmflows-bridge-${server.server_id}`, version: "1.0.0" },
        { capabilities: {} },
      );
      await client.connect(transport);
    } catch (err) {
      console.error(`[mcp-bridge] Failed to start ${server.server_id} (${server.command}):`, err);
      continue;
    }

    let tools: any[];
    try {
      const result = await client.listTools();
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

      api.registerTool({
        name: toolName,
        label: tool.name,
        description: tool.description || `Tool from ${server.server_id}`,
        promptSnippet: tool.description || "",
        parameters,
        async execute(_toolCallId: string, params: Record<string, unknown>) {
          try {
            const result = await client.callTool({
              name: toolName,
              arguments: params,
            });
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
