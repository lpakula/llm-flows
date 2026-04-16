import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { InboxItem, CompletedRunItem } from "@/api/types";
import { Check, UserCheck, ArrowRight, ChevronRight, ChevronDown, CheckCircle, Archive } from "lucide-react";
import { MarkdownContent } from "@/components/MarkdownContent";
import { AttachmentsGrid } from "@/components/AttachmentsGrid";
import { formatSeconds } from "@/lib/format";

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
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-5 py-3.5 flex items-center gap-3 text-left hover:bg-gray-800/40 transition"
      >
        <UserCheck size={14} className="text-amber-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-200 truncate">
              {item.flow_name || "Run"}
            </span>
            <span className="text-[10px] uppercase tracking-wider font-medium px-1.5 py-0.5 rounded-full flex-shrink-0 bg-amber-500/15 text-amber-400">
              manual
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-gray-500 mt-1">
            <span>{item.space_name}</span>
            <span className="text-gray-700">·</span>
            <span>{item.step_name.replace(/-/g, " ")}</span>
            <span className="text-gray-700">·</span>
            <span className="font-mono">{item.run_id}</span>
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

      {expanded && (
        <div className="px-5 pb-4 border-t border-gray-800">
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

          <div className="space-y-2">
            <textarea
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && response.trim()) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              placeholder="Type your response..."
              rows={1}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-600 focus:border-gray-600 resize-none overflow-hidden"
              disabled={submitting}
              autoFocus
              onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; }}
            />
            <div className="flex items-center gap-3">
              <button
                onClick={handleSubmit}
                disabled={submitting || !response.trim()}
                className="inline-flex items-center gap-1 px-2 py-1 text-green-500 hover:text-green-400 disabled:opacity-40 text-xs font-medium transition"
              >
                <Check size={12} />
                {submitting ? "..." : "Submit"}
              </button>
              <span className="text-[10px] text-gray-700 flex-1">Enter to submit, Shift+Enter for new line</span>
              <button
                onClick={() => navigate(`/space/${item.space_id}/run/${item.run_id}`)}
                className="text-[11px] text-blue-500 hover:text-blue-400 inline-flex items-center gap-0.5"
              >
                View run <ArrowRight size={10} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CompletedRunCard({ item, onArchive }: { item: CompletedRunItem; onArchive: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="flex items-center">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex-1 min-w-0 px-5 py-3.5 flex items-center gap-3 text-left hover:bg-gray-800/40 transition"
        >
          <CheckCircle size={14} className="text-green-500 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-200 truncate">
                {item.flow_name || "Run"}
              </span>
              <span className="text-[10px] uppercase tracking-wider font-medium px-1.5 py-0.5 rounded-full flex-shrink-0 bg-green-500/15 text-green-400">
                {item.outcome || "completed"}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-[11px] text-gray-500 mt-1">
              <span>{item.space_name}</span>
              {item.duration_seconds != null && (
                <>
                  <span className="text-gray-700">·</span>
                  <span>{formatSeconds(item.duration_seconds)}</span>
                </>
              )}
              <span className="text-gray-700">·</span>
              <span className="font-mono">{item.run_id}</span>
            </div>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <span className="text-[11px] text-gray-600">{timeAgo(item.completed_at)}</span>
            {expanded ? (
              <ChevronDown size={16} className="text-gray-500" />
            ) : (
              <ChevronRight size={16} className="text-gray-500" />
            )}
          </div>
        </button>
      </div>

      {expanded && (
        <div className="px-5 pb-4 border-t border-gray-800">
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mt-4 mb-3 max-h-96 overflow-y-auto">
            <MarkdownContent text={item.summary} className="text-sm text-gray-300" />
            <AttachmentsGrid files={item.attachments || []} />
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              onClick={() => navigate(`/space/${item.space_id}/run/${item.run_id}`)}
              className="text-xs text-blue-400 hover:text-blue-300 transition"
            >
              View run
            </button>
            <span className="text-gray-700">·</span>
            <button
              onClick={() => onArchive(item.inbox_id)}
              className="text-xs text-green-500 hover:text-green-400 inline-flex items-center gap-1 transition"
            >
              <Archive size={11} />
              Archive
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function InboxView() {
  const [awaiting, setAwaiting] = useState<InboxItem[]>([]);
  const [completed, setCompleted] = useState<CompletedRunItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getInbox();
      setAwaiting(data.awaiting);
      setCompleted(data.completed);
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

  const handleArchive = async (inboxId: string) => {
    try {
      await api.archiveInboxItem(inboxId);
      await refresh();
    } catch (e) {
      console.error("Archive error:", e);
    }
  };

  const isEmpty = awaiting.length === 0 && completed.length === 0;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-1">Inbox</h2>
        <p className="text-sm text-gray-500">
          Steps waiting for your action and recently completed runs.
        </p>
      </div>

      {loading && <div className="text-gray-500">Loading...</div>}

      {!loading && isEmpty && (
        <div className="text-center py-16 text-gray-600">
          <Check size={32} className="mx-auto mb-3 text-gray-700" />
          <p className="text-sm">Nothing requires your attention right now.</p>
        </div>
      )}

      {awaiting.length > 0 && (
        <div className="space-y-3 mb-6">
          {awaiting.map((item) => (
            <InboxCard key={item.step_run_id} item={item} onRespond={handleRespond} />
          ))}
        </div>
      )}

      {completed.length > 0 && (
        <>
          {awaiting.length > 0 && (
            <div className="text-[10px] uppercase tracking-wide text-gray-600 mb-3">Recently completed</div>
          )}
          <div className="space-y-3">
            {completed.map((item) => (
              <CompletedRunCard key={item.inbox_id} item={item} onArchive={handleArchive} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
