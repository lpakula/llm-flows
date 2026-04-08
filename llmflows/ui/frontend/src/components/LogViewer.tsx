import { useRef, useEffect, useState, useCallback } from "react";
import type { LogEntry } from "@/api/types";

interface Props {
  entries: LogEntry[];
  streaming: boolean;
  /** Notifies parent so layout (e.g. fixed height) can shrink when collapsed */
  onExpandedChange?: (expanded: boolean) => void;
}

function OutputBlock({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const lines = entry.lines || [];
  const preview = lines.slice(0, 3);

  if (lines.length <= 3) {
    return (
      <div className="text-xs text-gray-500 font-mono whitespace-pre-wrap">
        {lines.join("\n")}
      </div>
    );
  }

  return (
    <div>
      <div className={`text-xs text-gray-500 font-mono whitespace-pre-wrap ${expanded ? "" : "ml-4"}`}>
        {expanded ? lines.join("\n") : preview.join("\n")}
      </div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-[10px] text-gray-600 hover:text-gray-400 mt-0.5"
      >
        {expanded ? "▲ collapse" : `▼ ${lines.length - 3} more lines`}
      </button>
    </div>
  );
}

export function LogViewer({ entries, streaming, onExpandedChange }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [agentLogOpen, setAgentLogOpen] = useState(true);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAtBottom(isAtBottom);
  }, []);

  useEffect(() => {
    if (atBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries, atBottom]);

  const copyLogs = () => {
    const text = entries
      .map((e) => {
        if (e.type === "output") return (e.lines || []).join("\n");
        return e.text || "";
      })
      .join("\n");
    navigator.clipboard.writeText(text);
  };

  return (
    <div className={`flex flex-col min-h-0 ${agentLogOpen ? "h-full" : "h-auto"}`}>
      <div className="flex items-center justify-between px-5 py-2 border-b border-gray-800 shrink-0">
        <button
          type="button"
          onClick={() => {
            setAgentLogOpen((o) => {
              const next = !o;
              onExpandedChange?.(next);
              return next;
            });
          }}
          aria-expanded={agentLogOpen}
          className="flex items-center gap-2 min-w-0 text-left rounded-lg -ml-1 pl-1 pr-2 py-0.5 hover:bg-gray-800/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50"
        >
          <span className="w-4 flex justify-center shrink-0 leading-none" aria-hidden>
            <span
              className={`text-[9px] text-gray-600 transition-transform inline-block ${agentLogOpen ? "rotate-90" : ""}`}
            >
              ▶
            </span>
          </span>
          <span className="text-[10px] uppercase tracking-wide text-gray-600">Agent log</span>
        </button>
        {entries.length > 0 && (
          <button
            type="button"
            onClick={copyLogs}
            className="text-[11px] text-gray-500 hover:text-gray-300 transition shrink-0"
          >
            Copy logs
          </button>
        )}
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={`min-h-0 font-mono text-xs space-y-0.5 px-5 overflow-y-auto ${
          agentLogOpen ? "flex-1 py-2" : "h-0 overflow-hidden py-0 pointer-events-none"
        }`}
      >
        {entries.map((entry, i) =>
          entry.type === "output" ? (
            <OutputBlock key={i} entry={entry} />
          ) : (
            <div key={i} className={entry.cls || "text-gray-400"}>
              {entry.text}
            </div>
          ),
        )}
        {entries.length === 0 && !streaming && (
          <div className="text-gray-600 italic">No logs</div>
        )}
      </div>
    </div>
  );
}
