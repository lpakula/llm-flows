import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { InboxItem } from "@/api/types";
import { Check, MessageSquare, UserCheck, ArrowRight, ChevronRight, ChevronDown } from "lucide-react";
import { MarkdownContent } from "@/components/MarkdownContent";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function InboxCard({
  item,
  onRespond,
}: {
  item: InboxItem;
  onRespond: (id: string, response: string) => Promise<void>;
}) {
  const [response, setResponse] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();
  const isPrompt = item.step_type === "prompt";

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onRespond(item.step_run_id, response);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      {/* Collapsed row — always visible */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-5 py-3.5 flex items-center gap-3 text-left hover:bg-gray-800/40 transition"
      >
        {isPrompt ? (
          <MessageSquare size={14} className="text-blue-400 flex-shrink-0" />
        ) : (
          <UserCheck size={14} className="text-amber-400 flex-shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-200 truncate">
              {item.task_name || "Unnamed task"}
            </span>
            <span
              className={`text-[10px] uppercase tracking-wider font-medium px-1.5 py-0.5 rounded-full flex-shrink-0 ${
                isPrompt
                  ? "bg-blue-500/15 text-blue-400"
                  : "bg-amber-500/15 text-amber-400"
              }`}
            >
              {item.step_type}
            </span>
          </div>
          {item.task_description && (
            <p className="text-xs text-gray-500 mt-0.5 truncate">{item.task_description}</p>
          )}
          <div className="flex items-center gap-1.5 text-[11px] text-gray-500 mt-1">
            <span>{item.project_name}</span>
            <span className="text-gray-700">·</span>
            <span>{item.flow_name || "—"}</span>
            <span className="text-gray-700">·</span>
            <span>{item.step_name.replace(/-/g, " ")}</span>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="text-[11px] text-gray-600">{timeAgo(item.awaiting_since)}</span>
          {expanded ? (
            <ChevronDown size={16} className="text-gray-500" />
          ) : (
            <ChevronRight size={16} className="text-gray-500" />
          )}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-5 pb-4 border-t border-gray-800">
          {/* Agent's message */}
          {item.user_message ? (
            <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mt-4 mb-4 max-h-80 overflow-y-auto">
              <MarkdownContent text={item.user_message} className="text-sm text-gray-300" />
            </div>
          ) : item.prompt ? (
            <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mt-4 mb-4">
              <p className="text-xs text-gray-400 whitespace-pre-wrap leading-relaxed line-clamp-6">
                {item.prompt}
              </p>
            </div>
          ) : <div className="mt-4" />}

          {/* Action area */}
          <div className="flex items-center justify-between">
            {isPrompt ? (
              <div className="flex items-center gap-2 flex-1">
                <input
                  type="text"
                  value={response}
                  onChange={(e) => setResponse(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && response.trim()) handleSubmit();
                  }}
                  placeholder="Type your answer..."
                  className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-600 focus:border-gray-600"
                  disabled={submitting}
                  autoFocus
                />
                <button
                  onClick={handleSubmit}
                  disabled={submitting || !response.trim()}
                  className="inline-flex items-center gap-1 px-2 py-1 text-green-500 hover:text-green-400 disabled:opacity-40 text-xs font-medium transition"
                >
                  <Check size={12} />
                  {submitting ? "..." : "Submit"}
                </button>
              </div>
            ) : (
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="inline-flex items-center gap-1 px-2 py-1 text-green-500 hover:text-green-400 disabled:opacity-40 text-xs font-medium transition"
              >
                <Check size={12} />
                {submitting ? "Confirming..." : "Mark as Done"}
              </button>
            )}
            <button
              onClick={() => navigate(`/project/${item.project_id}/task/${item.task_id}`)}
              className="text-[11px] text-blue-500 hover:text-blue-400 inline-flex items-center gap-0.5 ml-3 flex-shrink-0"
            >
              View task <ArrowRight size={10} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function InboxView() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setItems(await api.getInbox());
    } catch (e) {
      console.error("Inbox load error:", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);
  useInterval(refresh, 5000);

  const handleRespond = async (stepRunId: string, response: string) => {
    await api.respondToStep(stepRunId, response);
    await refresh();
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-1">Inbox</h2>
        <p className="text-sm text-gray-500">
          Steps waiting for your action across all projects.
        </p>
      </div>

      {loading && <div className="text-gray-500">Loading...</div>}

      {!loading && items.length === 0 && (
        <div className="text-center py-16 text-gray-600">
          <Check size={32} className="mx-auto mb-3 text-gray-700" />
          <p className="text-sm">Nothing requires your attention right now.</p>
        </div>
      )}

      {items.length > 0 && (
        <div className="space-y-3">
          {items.map((item) => (
            <InboxCard key={item.step_run_id} item={item} onRespond={handleRespond} />
          ))}
        </div>
      )}
    </div>
  );
}
