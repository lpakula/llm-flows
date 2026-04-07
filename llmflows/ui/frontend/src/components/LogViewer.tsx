import { useRef, useEffect, useState, useCallback } from "react";
import type { LogEntry } from "@/api/types";

interface Props {
  entries: LogEntry[];
  streaming: boolean;
}

function OutputBlock({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const lines = entry.lines || [];
  const preview = lines.slice(0, 3);

  if (lines.length <= 3) {
    return (
      <div className="ml-4 text-xs text-gray-500 font-mono whitespace-pre-wrap">
        {lines.join("\n")}
      </div>
    );
  }

  return (
    <div className="ml-4">
      <div className="text-xs text-gray-500 font-mono whitespace-pre-wrap">
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

export function LogViewer({ entries, streaming }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

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
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-800">
        <div className="flex items-center gap-2">
          {streaming && (
            <span className="flex items-center gap-1 text-xs text-yellow-400">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
              Streaming
            </span>
          )}
          {!streaming && entries.length > 0 && (
            <span className="text-xs text-gray-500">{entries.length} entries</span>
          )}
        </div>
        {entries.length > 0 && (
          <button onClick={copyLogs} className="text-[11px] text-gray-500 hover:text-gray-300 transition">
            Copy
          </button>
        )}
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 font-mono text-xs space-y-0.5"
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
