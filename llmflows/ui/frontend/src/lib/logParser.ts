import type { LogEntry } from "@/api/types";

function shorten(path: string, prefix: string | null): string {
  if (!path) return "?";
  if (prefix && path.startsWith(prefix)) return path.slice(prefix.length);
  return path;
}

function extractTool(tc: Record<string, unknown>): { name: string; data: Record<string, unknown> } {
  for (const key of [
    "readToolCall", "writeToolCall", "editToolCall", "shellToolCall",
    "grepToolCall", "globToolCall", "listToolCall", "deleteToolCall",
    "updateTodosToolCall", "function",
  ]) {
    if (tc[key]) return { name: key, data: tc[key] as Record<string, unknown> };
  }
  for (const [key, val] of Object.entries(tc)) {
    if (val && typeof val === "object") return { name: key, data: val as Record<string, unknown> };
  }
  return { name: "unknown", data: {} };
}

function describeClaudeToolUse(c: Record<string, unknown>, prefix: string | null): string {
  const name = (c.name as string) || "tool";
  const input = (c.input as Record<string, string>) || {};
  if (input.command) return `${name}: ${input.command.slice(0, 100)}`;
  if (input.file_path || input.path) return `${name}: ${shorten(input.file_path || input.path, prefix)}`;
  if (input.pattern) return `${name}: ${input.pattern}`;
  if (input.glob_pattern) return `${name}: ${input.glob_pattern}`;
  return name;
}

function describeToolStart(tc: Record<string, unknown>, prefix: string | null): string {
  const { name, data } = extractTool(tc);
  const args = (data.args as Record<string, string>) || {};

  if (name === "readToolCall") return `Read ${shorten(args.path, prefix)}`;
  if (name === "writeToolCall") return `Write ${shorten(args.path, prefix)}`;
  if (name === "editToolCall") return `Edit ${shorten(args.path, prefix)}`;
  if (name === "shellToolCall") return `Shell: ${(args.command || "?").slice(0, 100)}`;
  if (name === "grepToolCall") return `Grep: ${args.pattern || "?"}`;
  if (name === "globToolCall") return `Glob: ${args.pattern || args.glob || "?"}`;
  if (name === "listToolCall") return `List ${shorten(args.path, prefix)}`;
  if (name === "deleteToolCall") return `Delete ${shorten(args.path, prefix)}`;
  if (name === "updateTodosToolCall") {
    const todos = (args.todos as unknown as unknown[]) || [];
    return `Update todos (${todos.length} items)`;
  }
  if (name === "function") {
    const fnName = (data.name as string) || "tool";
    try {
      const fnArgs = JSON.parse((data.arguments as string) || "{}");
      if (fnArgs.command) return `${fnName}: ${fnArgs.command.slice(0, 100)}`;
      if (fnArgs.path) return `${fnName}: ${shorten(fnArgs.path, prefix)}`;
      if (fnArgs.pattern) return `${fnName}: ${fnArgs.pattern}`;
    } catch { /* ignore */ }
    return fnName;
  }

  const label = name.replace(/ToolCall$/, "").replace(/_/g, " ");
  const detail = args.path || args.pattern || args.command || "";
  return detail ? `${label}: ${shorten(String(detail), prefix).slice(0, 80)}` : label;
}

function describeToolDone(tc: Record<string, unknown>, prefix: string | null): { text: string; output?: string } {
  const { name, data } = extractTool(tc);
  const result = (data.result as Record<string, unknown>) || {};
  const success = (result.success as Record<string, unknown>) || {};
  const args = (data.args as Record<string, string>) || {};

  if (name === "readToolCall" && success) {
    return { text: `Read ${shorten(args.path, prefix)} (${success.totalLines || "?"} lines)` };
  }
  if (name === "writeToolCall" && success) {
    return { text: `Wrote ${shorten((success.path as string) || args.path, prefix)} (${success.linesCreated || "?"} lines)` };
  }
  if (name === "editToolCall" && success) {
    return { text: `Edited ${shorten(args.path, prefix)}` };
  }
  if (name === "shellToolCall") {
    const exitCode = (success.exitCode ?? success.exit_code) as number | undefined;
    const stdout = ((success.stdout || success.output || "") as string).trim();
    const header = exitCode !== undefined ? `Shell completed (exit ${exitCode})` : "Shell completed";
    return { text: header, output: stdout || undefined };
  }
  if (name === "grepToolCall") return { text: "Grep completed" };
  if (name === "globToolCall") return { text: "Glob completed" };
  if (name === "updateTodosToolCall") return { text: "Todos updated" };
  if (name === "function") return { text: `${(data.name as string) || "tool"} completed` };

  const label = name.replace(/ToolCall$/, "").replace(/_/g, " ");
  return { text: `${label} completed` };
}

// ── Pi event helpers ──────────────────────────────────────────────────────────

function describePiToolCall(name: string, args: Record<string, string>, prefix: string | null): string {
  if (name === "read") return `Read ${shorten(args.path || args.file_path || "?", prefix)}`;
  if (name === "write") return `Write ${shorten(args.path || args.file_path || "?", prefix)}`;
  if (name === "edit") return `Edit ${shorten(args.path || args.file_path || "?", prefix)}`;
  if (name === "bash" || name === "shell") return `Shell: ${(args.command || "?").slice(0, 100)}`;
  if (name === "grep" || name === "search") return `Grep: ${args.pattern || args.query || "?"}`;
  if (name === "glob" || name === "list") return `Glob: ${args.pattern || args.glob || "?"}`;
  return `${name}: ${(args.path || args.command || args.pattern || "").slice(0, 80) || "..."}`;
}

function isPiEvent(event: Record<string, unknown>): boolean {
  const t = event.type as string | undefined;
  if (t && /^(session|agent_|turn_|message_|tool_execution_)/.test(t)) return true;
  return event.role !== undefined;
}

function parsePiMessage(msg: Record<string, unknown>, prefix: string | null): LogEntry[] | null {
  const role = msg.role as string | undefined;
  if (!role || role === "user") return null;

  const content = msg.content as Array<Record<string, unknown>> | undefined;
  if (!content || !Array.isArray(content)) return null;

  if (role === "assistant") {
    if (!msg.stopReason && !msg.textSignature) return null;
    const entries: LogEntry[] = [];
    for (const c of content) {
      if (c.type === "text" && (c.text as string)?.trim()) {
        entries.push({ text: (c.text as string).trim(), cls: "text-blue-300" });
      } else if (c.type === "toolCall" && c.name && msg.stopReason === "toolUse") {
        const args = (c.arguments as Record<string, string>) || {};
        entries.push({ text: `  \u25b6 ${describePiToolCall(c.name as string, args, prefix)}`, cls: "text-yellow-400" });
      }
    }
    return entries.length ? entries : null;
  }

  if (role === "toolResult") {
    const isErr = msg.isError === true;
    const toolName = (msg.toolName as string) || "tool";
    const texts = content.map(c => (c.text as string) || "").filter(Boolean);
    const output = texts.join("\n").trim();
    const header = isErr ? `${toolName} error` : `${toolName} completed`;
    const entries: LogEntry[] = [{ text: `  \u2714 ${header}`, cls: isErr ? "text-red-400" : "text-green-400" }];
    if (output && output.length < 2000) {
      entries.push({ type: "output", lines: output.split("\n"), expanded: false, cls: "text-gray-500" });
    }
    return entries;
  }

  return null;
}

function parsePiEvent(event: Record<string, unknown>, prefix: string | null): LogEntry[] | null {
  const t = event.type as string | undefined;

  if (t === "session") return [{ text: `--- Pi session started ---`, cls: "text-gray-500" }];
  if (t === "agent_start" || t === "turn_start" || t === "turn_end") return null;
  if (t === "message_start" || t === "message_update") return null;
  if (t === "agent_end") return [{ text: `--- Pi agent finished ---`, cls: "text-gray-500" }];

  if (t === "tool_execution_start") {
    const name = (event.toolName as string) || "tool";
    const args = (event.args as Record<string, string>) || {};
    return [{ text: `  \u25b6 ${describePiToolCall(name, args, prefix)}`, cls: "text-yellow-400" }];
  }
  if (t === "tool_execution_end") {
    const name = (event.toolName as string) || "tool";
    const isErr = event.isError === true;
    const result = event.result as Record<string, unknown> | undefined;
    const content = (result?.content as Array<{ text?: string }>) || [];
    const output = content.map(c => c.text || "").filter(Boolean).join("\n").trim();
    const header = isErr ? `${name} error` : `${name} completed`;
    const entries: LogEntry[] = [{ text: `  \u2714 ${header}`, cls: isErr ? "text-red-400" : "text-green-400" }];
    if (output && output.length < 2000) {
      entries.push({ type: "output", lines: output.split("\n"), expanded: false, cls: "text-gray-500" });
    }
    return entries;
  }

  if (t === "message_end") {
    const msg = event.message as Record<string, unknown> | undefined;
    return msg ? parsePiMessage(msg, prefix) : null;
  }

  if (event.role) return parsePiMessage(event as Record<string, unknown>, prefix);

  return null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function parseLogEvent(event: any, prefix: string | null): LogEntry[] | null {
  if (isPiEvent(event)) return parsePiEvent(event, prefix);

  switch (event.type) {
    case "system":
      return [{ text: `--- Session started (${event.model || "agent"}) ---`, cls: "text-gray-500" }];

    case "assistant": {
      const parts = (event.message?.content || []).filter((c: { type: string }) => c.type !== "thinking");
      const entries: LogEntry[] = [];
      for (const c of parts) {
        if (c.type === "text" && c.text?.trim()) {
          entries.push({ text: c.text.trim(), cls: "text-blue-300" });
        } else if (c.type === "tool_use") {
          const label = describeClaudeToolUse(c, prefix);
          entries.push({ text: `  \u25b6 ${label}`, cls: "text-yellow-400" });
        }
      }
      return entries.length ? entries : null;
    }

    case "user": {
      const parts = event.message?.content || [];
      const entries: LogEntry[] = [];
      for (const c of parts) {
        if (c.type !== "tool_result") continue;
        const stdout = (event.tool_use_result?.stdout || c.content || "").trim();
        const isErr = c.is_error || false;
        const header = isErr ? "Tool error" : "Tool completed";
        entries.push({ text: `  \u2714 ${header}`, cls: isErr ? "text-red-400" : "text-green-400" });
        if (stdout) {
          entries.push({ type: "output", lines: stdout.split("\n"), expanded: false, cls: "text-gray-500" });
        }
      }
      return entries.length ? entries : null;
    }

    case "tool_call": {
      const tc = event.tool_call || {};
      if (event.subtype === "started") {
        return [{ text: `  \u25b6 ${describeToolStart(tc, prefix)}`, cls: "text-yellow-400" }];
      }
      if (event.subtype === "completed") {
        const info = describeToolDone(tc, prefix);
        const entries: LogEntry[] = [{ text: `  \u2714 ${info.text}`, cls: "text-green-400" }];
        if (info.output) {
          entries.push({ type: "output", lines: info.output.split("\n"), expanded: false, cls: "text-gray-500" });
        }
        return entries;
      }
      return null;
    }

    case "result":
      return [{ text: `--- Done (${((event.duration_ms || 0) / 1000).toFixed(1)}s) ---`, cls: "text-gray-500" }];

    case "thinking":
      return null;

    case "raw":
      return event.text ? [{ text: event.text, cls: "text-red-400" }] : null;

    default: {
      const msg = event.message || event.error || event.text || event.data || JSON.stringify(event);
      const text = typeof msg === "string" ? msg : JSON.stringify(msg);
      if (!text.trim() || text === "{}") return null;
      const cls =
        event.type === "error" || text.toLowerCase().includes("error") || text.toLowerCase().includes("cannot")
          ? "text-red-400"
          : "text-gray-400";
      return [{ text: text.trim(), cls }];
    }
  }
}
