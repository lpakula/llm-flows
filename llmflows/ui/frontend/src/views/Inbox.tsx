import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { InboxItem, FlowImprovementItem, CompletedRunItem } from "@/api/types";
import { Check, UserCheck, ChevronRight, ChevronDown, Archive, Sparkles } from "lucide-react";
import { MarkdownContent } from "@/components/MarkdownContent";
import { AttachmentsGrid } from "@/components/AttachmentsGrid";
import { formatSeconds } from "@/lib/format";

type AnyInboxItem = InboxItem | FlowImprovementItem | CompletedRunItem;

interface InboxGroup {
  key: string;
  flowName: string;
  spaceName: string;
  spaceId: string;
  flowId: string;
  awaiting: (InboxItem | FlowImprovementItem)[];
  completed: CompletedRunItem[];
}

function groupInboxItems(
  awaiting: (InboxItem | FlowImprovementItem)[],
  completed: CompletedRunItem[],
): InboxGroup[] {
  const map = new Map<string, InboxGroup>();
  const getOrCreate = (item: AnyInboxItem) => {
    const key = `${item.flow_id}::${item.space_id}`;
    let group = map.get(key);
    if (!group) {
      group = {
        key,
        flowName: item.flow_name,
        spaceName: item.space_name,
        spaceId: item.space_id,
        flowId: item.flow_id,
        awaiting: [],
        completed: [],
      };
      map.set(key, group);
    }
    return group;
  };

  for (const item of awaiting) getOrCreate(item).awaiting.push(item);
  for (const item of completed) getOrCreate(item).completed.push(item);

  const groups = Array.from(map.values());
  groups.sort((a, b) => {
    if (a.awaiting.length > 0 && b.awaiting.length === 0) return -1;
    if (a.awaiting.length === 0 && b.awaiting.length > 0) return 1;
    return 0;
  });
  return groups;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function flowUrl(spaceId: string, flowId: string) {
  if (flowId) return `/space/${spaceId}/flow/${flowId}`;
  return `/space/${spaceId}/flows`;
}

const ERROR_OUTCOMES = new Set(["timeout", "max_spend", "interrupted", "error"]);

function outcomePillClass(outcome: string) {
  if (ERROR_OUTCOMES.has(outcome)) return "bg-red-500/15 text-red-400";
  return "bg-green-500/15 text-green-400";
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
  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onRespond(item.step_run_id, response);
    } finally {
      setSubmitting(false);
    }
  };

  const title = item.inbox_title || item.step_name.replace(/-/g, " ") || item.flow_name || "Run";

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
              {title}
            </span>
            <span className="text-[10px] uppercase tracking-wider font-medium px-1.5 py-0.5 rounded-full flex-shrink-0 bg-amber-500/15 text-amber-400">
              HITL
            </span>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-gray-500 mt-1">
            <span>{item.step_name.replace(/-/g, " ")}</span>
            <span className="font-mono">{item.run_id.slice(0, 8)}</span>
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
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function FlowImprovementCard({
  item,
  onApprove,
  onReject,
  onDiscard,
}: {
  item: FlowImprovementItem;
  onApprove: (inboxId: string, selection?: string) => Promise<void>;
  onReject: (inboxId: string, reason: string) => Promise<void>;
  onDiscard: (inboxId: string) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [selection, setSelection] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [acting, setActing] = useState(false);

  const handleApprove = async () => {
    setActing(true);
    try {
      await onApprove(item.inbox_id, selection.trim() || undefined);
    } finally {
      setActing(false);
    }
  };

  const handleReject = async () => {
    setActing(true);
    try {
      await onReject(item.inbox_id, rejectReason);
    } finally {
      setActing(false);
      setRejecting(false);
      setRejectReason("");
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-5 py-3.5 flex items-center gap-3 text-left hover:bg-gray-800/40 transition"
      >
        <Sparkles size={14} className="text-purple-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-200">
              Flow analysis report
            </span>
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
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mt-4 mb-4 max-h-80 overflow-y-auto">
            <MarkdownContent text={item.summary} className="text-sm text-gray-300" />
          </div>

          {rejecting ? (
            <div className="space-y-2">
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleReject();
                  }
                  if (e.key === "Escape") {
                    setRejecting(false);
                    setRejectReason("");
                  }
                }}
                placeholder="Why are you rejecting this? (optional, saved to flow memory)"
                rows={1}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-600 focus:border-gray-600 resize-none overflow-hidden"
                disabled={acting}
                autoFocus
                onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; }}
              />
              <div className="flex items-center gap-3">
                <button
                  onClick={handleReject}
                  disabled={acting}
                  className="text-xs font-medium text-red-500 hover:text-red-400 disabled:opacity-40 transition"
                >
                  {acting ? "..." : "Confirm reject"}
                </button>
                <button
                  onClick={() => { setRejecting(false); setRejectReason(""); }}
                  disabled={acting}
                  className="text-xs font-medium text-gray-500 hover:text-gray-300 disabled:opacity-40 transition"
                >
                  Cancel
                </button>
                <span className="text-[10px] text-gray-700 flex-1">Enter to confirm, Esc to cancel</span>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <textarea
                value={selection}
                onChange={(e) => setSelection(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleApprove();
                  }
                }}
                placeholder="Which improvements to apply? (empty = all)"
                rows={1}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-600 focus:border-gray-600 resize-none overflow-hidden"
                disabled={acting}
                onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; }}
              />
              <div className="flex items-center gap-3">
                <button
                  onClick={handleApprove}
                  disabled={acting}
                  className="text-xs font-medium text-green-500 hover:text-green-400 disabled:opacity-40 transition"
                >
                  {acting ? "Applying..." : "Approve"}
                </button>
                <button
                  onClick={() => setRejecting(true)}
                  disabled={acting}
                  className="text-xs font-medium text-gray-500 hover:text-gray-300 disabled:opacity-40 transition"
                >
                  Reject
                </button>
                <button
                  onClick={async () => { setActing(true); try { await onDiscard(item.inbox_id); } finally { setActing(false); } }}
                  disabled={acting}
                  className="text-xs font-medium text-gray-500 hover:text-gray-300 disabled:opacity-40 transition"
                >
                  Discard
                </button>
                <span className="flex-1" />
                <span className="text-[10px] text-gray-700">Enter to approve</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CompletedRunCard({ item, onArchive }: { item: CompletedRunItem; onArchive: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const title = item.inbox_title || item.flow_name || "Run";
  const preview = item.inbox_body || "";
  const truncatedPreview = preview.length > 140 ? preview.slice(0, 140) + "…" : preview;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div
        onClick={() => setExpanded((v) => !v)}
        className="px-5 py-3.5 flex items-center gap-3 cursor-pointer hover:bg-gray-800/40 transition"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-200 truncate">
              {title}
            </span>
            <span className={`text-[10px] uppercase tracking-wider font-medium px-1.5 py-0.5 rounded-full flex-shrink-0 ${outcomePillClass(item.outcome)}`}>
              {item.outcome || "completed"}
            </span>
          </div>
          {truncatedPreview && (
            <p className="text-xs text-gray-400 mt-1 line-clamp-2">{truncatedPreview}</p>
          )}
          <div className="flex items-center gap-3 text-[11px] text-gray-500 mt-1.5">
            {item.duration_seconds != null && (
              <span><span className="text-gray-600">Time:</span> {formatSeconds(item.duration_seconds)}</span>
            )}
            {item.cost_usd != null && (
              <span><span className="text-gray-600">Cost:</span> ${item.cost_usd.toFixed(4)}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[11px] text-gray-600">{timeAgo(item.completed_at)}</span>
          <button
            onClick={(e) => { e.stopPropagation(); onArchive(item.inbox_id); }}
            className="p-1.5 rounded-md text-gray-500 hover:text-green-400 hover:bg-gray-800 transition"
            title="Archive"
          >
            <Archive size={13} />
          </button>
          {expanded ? (
            <ChevronDown size={16} className="text-gray-500" />
          ) : (
            <ChevronRight size={16} className="text-gray-500" />
          )}
        </div>
      </div>

      {expanded && (
        <div className="px-5 pb-4 border-t border-gray-800">
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-4 py-3 mt-4 max-h-96 overflow-y-auto">
            <MarkdownContent text={item.summary} className="text-sm text-gray-300" />
            <AttachmentsGrid files={item.attachments || []} />
          </div>
        </div>
      )}
    </div>
  );
}

function isFlowImprovement(item: InboxItem | FlowImprovementItem): item is FlowImprovementItem {
  return "type" in item && item.type === "flow_improvement";
}

export function InboxView() {
  const [awaiting, setAwaiting] = useState<(InboxItem | FlowImprovementItem)[]>([]);
  const [completed, setCompleted] = useState<CompletedRunItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [archivingGroups, setArchivingGroups] = useState<Set<string>>(new Set());
  const navigate = useNavigate();

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

  const groups = useMemo(
    () => groupInboxItems(awaiting, completed),
    [awaiting, completed],
  );

  const handleRespond = async (stepRunId: string, response: string) => {
    await api.respondToStep(stepRunId, response);
    await refresh();
    window.dispatchEvent(new Event("inbox-updated"));
  };

  const handleArchive = async (inboxId: string) => {
    try {
      await api.archiveInboxItem(inboxId);
      await refresh();
      window.dispatchEvent(new Event("inbox-updated"));
    } catch (e) {
      console.error("Archive error:", e);
    }
  };

  const handleArchiveGroup = async (group: InboxGroup) => {
    const ids = group.completed.map((c) => c.inbox_id);
    if (ids.length === 0) return;
    setArchivingGroups((s) => new Set(s).add(group.key));
    try {
      await api.archiveInboxBatch(ids);
      await refresh();
      window.dispatchEvent(new Event("inbox-updated"));
    } catch (e) {
      console.error("Archive group error:", e);
    } finally {
      setArchivingGroups((s) => { const n = new Set(s); n.delete(group.key); return n; });
    }
  };

  const handleApproveImprovement = async (inboxId: string, selection?: string) => {
    try {
      await api.approveImprovement(inboxId, selection);
      await refresh();
      window.dispatchEvent(new Event("inbox-updated"));
    } catch (e) {
      console.error("Approve improvement error:", e);
    }
  };

  const handleRejectImprovement = async (inboxId: string, reason: string) => {
    try {
      await api.rejectImprovement(inboxId, reason);
      await refresh();
      window.dispatchEvent(new Event("inbox-updated"));
    } catch (e) {
      console.error("Reject improvement error:", e);
    }
  };

  const isEmpty = awaiting.length === 0 && completed.length === 0;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div>
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

        {groups.map((group) => (
          <div key={group.key} className="mb-6">
            <div className="flex items-center gap-2 mb-2.5">
              <button
                onClick={() => navigate(flowUrl(group.spaceId, group.flowId))}
                className="text-xs font-medium text-blue-400 hover:text-blue-300 bg-blue-500/10 px-2 py-1 rounded transition truncate"
              >
                {group.flowName}
              </button>
              <span className="text-xs text-gray-600 truncate">{group.spaceName}</span>
              <span className="flex-1" />
              {group.completed.length > 0 && (
                <button
                  onClick={() => handleArchiveGroup(group)}
                  disabled={archivingGroups.has(group.key)}
                  className="inline-flex items-center gap-1 text-[11px] text-gray-600 hover:text-green-400 disabled:opacity-40 transition"
                  title="Archive all completed in this group"
                >
                  <Archive size={12} />
                  Archive{group.completed.length > 1 ? ` (${group.completed.length})` : ""}
                </button>
              )}
            </div>

            <div className="space-y-2">
              {group.awaiting.map((item) =>
                isFlowImprovement(item) ? (
                  <FlowImprovementCard
                    key={item.inbox_id}
                    item={item}
                    onApprove={handleApproveImprovement}
                    onReject={handleRejectImprovement}
                    onDiscard={handleArchive}
                  />
                ) : (
                  <InboxCard key={item.step_run_id} item={item} onRespond={handleRespond} />
                ),
              )}
              {group.completed.map((item) => (
                <CompletedRunCard key={item.inbox_id} item={item} onArchive={handleArchive} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
