import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { InboxItem } from "@/api/types";
import { CheckCircle, MessageSquare, ArrowRight } from "lucide-react";
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
      <div className="px-5 py-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            {isPrompt ? (
              <MessageSquare size={16} className="text-blue-400 flex-shrink-0" />
            ) : (
              <CheckCircle size={16} className="text-amber-400 flex-shrink-0" />
            )}
            <div className="min-w-0">
              <h3 className="text-sm font-medium text-gray-200 truncate">
                {item.step_name.replace(/-/g, " ")}
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">
                {item.project_name} / {item.task_name || "Unnamed task"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span
              className={`text-[10px] uppercase tracking-wider font-medium px-2 py-0.5 rounded-full ${
                isPrompt
                  ? "bg-blue-500/15 text-blue-400"
                  : "bg-amber-500/15 text-amber-400"
              }`}
            >
              {item.step_type}
            </span>
            <span className="text-[11px] text-gray-600">{timeAgo(item.awaiting_since)}</span>
          </div>
        </div>

        {/* Agent's human-readable message */}
        {item.user_message ? (
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mb-4 max-h-80 overflow-y-auto">
            <MarkdownContent text={item.user_message} className="text-sm text-gray-300" />
          </div>
        ) : item.prompt ? (
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mb-4">
            <p className="text-xs text-gray-400 whitespace-pre-wrap leading-relaxed line-clamp-6">
              {item.prompt}
            </p>
          </div>
        ) : null}

        {/* Flow context */}
        <div className="flex items-center gap-1.5 text-[11px] text-gray-600 mb-4">
          <span>Flow: {item.flow_name || "—"}</span>
          <span className="text-gray-700">·</span>
          <span>Step {item.step_position + 1}</span>
          <span className="text-gray-700">·</span>
          <button
            onClick={() => navigate(`/project/${item.project_id}/task/${item.task_id}`)}
            className="text-blue-500 hover:text-blue-400 inline-flex items-center gap-0.5"
          >
            View task <ArrowRight size={10} />
          </button>
        </div>

        {/* Action area */}
        {isPrompt ? (
          <div className="flex gap-2">
            <input
              type="text"
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && response.trim()) handleSubmit();
              }}
              placeholder="Type your answer..."
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:border-blue-500"
              disabled={submitting}
            />
            <button
              onClick={handleSubmit}
              disabled={submitting || !response.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition"
            >
              {submitting ? "..." : "Submit"}
            </button>
          </div>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="w-full px-4 py-2.5 bg-amber-600/90 hover:bg-amber-500 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition flex items-center justify-center gap-2"
          >
            <CheckCircle size={14} />
            {submitting ? "Confirming..." : "Mark as Done"}
          </button>
        )}
      </div>
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
          <CheckCircle size={32} className="mx-auto mb-3 text-gray-700" />
          <p className="text-sm">Nothing requires your attention right now.</p>
        </div>
      )}

      {items.length > 0 && (
        <div className="max-w-2xl space-y-3">
          {items.map((item) => (
            <InboxCard key={item.step_run_id} item={item} onRespond={handleRespond} />
          ))}
        </div>
      )}
    </div>
  );
}
