import { useEffect, useRef, useState, useCallback } from "react";
import type { LogEntry } from "@/api/types";
import { parseLogEvent } from "@/lib/logParser";

const MAX_ENTRIES = 500;
const TRIM_TO = 400;

export function useLogStream(url: string | null, worktreePrefix?: string | null) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [streaming, setStreaming] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  const stop = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    setStreaming(false);
  }, []);

  useEffect(() => {
    if (!url) {
      stop();
      return;
    }

    stop();
    setEntries([]);
    setStreaming(true);

    const source = new EventSource(url);
    sourceRef.current = source;

    source.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        if (event.type === "done") {
          setStreaming(false);
          source.close();
          return;
        }
        const parsed = parseLogEvent(event, worktreePrefix ?? null);
        if (parsed) {
          setEntries((prev) => {
            const next = [...prev, ...parsed];
            return next.length > MAX_ENTRIES ? next.slice(-TRIM_TO) : next;
          });
        }
      } catch {
        // ignore parse errors
      }
    };

    source.onerror = () => {
      setStreaming(false);
      source.close();
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [url, worktreePrefix, stop]);

  const clear = useCallback(() => setEntries([]), []);

  return { entries, streaming, stop, clear };
}
