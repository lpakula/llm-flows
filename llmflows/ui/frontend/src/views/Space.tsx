import { useState, useEffect, useCallback, Fragment } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { FlowRun, Flow, SpaceSettings } from "@/api/types";
import { statusBadge, statusDot, displayStatus, duration, formatSeconds } from "@/lib/format";
import { ScheduleModal } from "@/components/RunModal";
import { Play } from "lucide-react";

// ── Column definitions ────────────────────────────────────────────────────────

const ERROR_OUTCOMES = new Set(["failed", "cancelled", "interrupted", "error", "timeout"]);

const RUN_STATUSES = [
  { key: "queue",       label: "Queue",       dot: "bg-blue-500",   text: "text-blue-400" },
  { key: "in_progress", label: "In Progress", dot: "bg-yellow-400", text: "text-yellow-400" },
  { key: "errored",     label: "Error",        dot: "bg-red-500",    text: "text-red-400" },
  { key: "completed",   label: "Completed",   dot: "bg-green-500",  text: "text-green-400" },
] as const;

type RunStatusKey = typeof RUN_STATUSES[number]["key"];

function runStatusKey(run: FlowRun): RunStatusKey {
  if (!run.started_at) return "queue";
  if (!run.completed_at) return "in_progress";
  if (run.outcome && ERROR_OUTCOMES.has(run.outcome)) return "errored";
  return "completed";
}

// ── Run row (list view) ──────────────────────────────────────────────────────

function shortDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function RunRow({
  run,
  onStop,
  onDelete,
  onClick,
}: {
  run: FlowRun;
  onStop: (run: FlowRun) => void;
  onDelete: (run: FlowRun) => void;
  onClick: (id: string) => void;
}) {
  const label = displayStatus(run);
  const status = runStatusKey(run);
  const dur = run.duration_seconds != null
    ? formatSeconds(run.duration_seconds)
    : duration(run.started_at, run.completed_at);

  return (
    <tr
      className="border-b border-gray-800/80 last:border-0 hover:bg-gray-800/40 cursor-pointer transition-colors group"
      onClick={() => onClick(run.id)}
    >
      <td className="py-2.5 whitespace-nowrap text-sm text-white font-medium" style={{ paddingLeft: "calc(0.75rem + 33px)", paddingRight: "0.75rem" }}>
        {run.flow_name || <span className="text-gray-700">—</span>}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <span className="text-xs text-gray-500 font-mono">{run.id}</span>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(label, run.outcome)}`} />
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${statusBadge(label)}`}>
            {label}
          </span>
        </div>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-gray-500 text-xs">
        {!run.completed_at && (run.current_step || <span className="text-gray-700">—</span>)}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-gray-500 text-xs tabular-nums">
        {shortDateTime(run.started_at || run.created_at)}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-gray-500 text-xs tabular-nums">
        {dur !== "-" && dur !== "—" ? dur : <span className="text-gray-700">—</span>}
      </td>
      <td className="px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end gap-2">
          {(status === "in_progress" || status === "queue") && (
            <button
              onClick={() => onStop(run)}
              className="text-xs text-red-400 hover:text-red-300 transition"
            >
              Stop
            </button>
          )}
          {status === "completed" && (
            <button
              onClick={() => onDelete(run)}
              className="text-xs text-gray-600 hover:text-red-400 transition opacity-0 group-hover:opacity-100"
            >
              Delete
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ── Run card (kanban view) ───────────────────────────────────────────────────

function RunCard({
  run,
  onStop,
  onDelete,
  onClick,
}: {
  run: FlowRun;
  onStop: (run: FlowRun) => void;
  onDelete: (run: FlowRun) => void;
  onClick: (id: string) => void;
}) {
  const label = displayStatus(run);
  const status = runStatusKey(run);
  const dur = run.duration_seconds != null
    ? formatSeconds(run.duration_seconds)
    : duration(run.started_at, run.completed_at);

  return (
    <div
      onClick={() => onClick(run.id)}
      className="bg-gray-900 border border-gray-800 rounded-xl p-3 hover:border-gray-600 cursor-pointer transition-colors group"
    >
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm text-white font-medium truncate">{run.flow_name || "—"}</span>
          <span className="text-[10px] text-gray-600 font-mono shrink-0">{run.id}</span>
        </div>
        <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded shrink-0 ${statusBadge(label)}`}>
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(label, run.outcome)}`} />
          {label}
        </span>
      </div>
      {!run.completed_at && run.current_step && (
        <div className="text-xs text-cyan-400 mb-1">Step: {run.current_step}</div>
      )}
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-800">
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-gray-600 tabular-nums">
            {shortDateTime(run.started_at || run.created_at)}
          </span>
          {dur !== "-" && dur !== "—" && (
            <span className="text-[10px] text-gray-700 tabular-nums">{dur}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {status === "completed" && (
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(run); }}
              className="text-xs text-gray-600 hover:text-red-400 transition opacity-0 group-hover:opacity-100"
            >
              Delete
            </button>
          )}
          {(status === "in_progress" || status === "queue") && (
            <button
              onClick={(e) => { e.stopPropagation(); onStop(run); }}
              className="text-xs text-red-400 hover:text-red-300 transition"
            >
              Stop
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Section / column order ───────────────────────────────────────────────────

const LIST_ORDER: RunStatusKey[] = ["queue", "in_progress", "errored", "completed"];
const KANBAN_ORDER: RunStatusKey[] = ["queue", "in_progress", "errored", "completed"];

// ── Main view ─────────────────────────────────────────────────────────────────

type ViewMode = "list" | "kanban";

export function SpaceView() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const navigate = useNavigate();

  const [flows, setFlows] = useState<Flow[]>([]);
  const [runs, setRuns] = useState<FlowRun[]>([]);
  const [maxConcurrent, setMaxConcurrent] = useState(1);
  const [viewMode, setViewMode] = useState<ViewMode>(() => (localStorage.getItem("board-view") as ViewMode) ?? "list");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ completed: true });
  const [scheduleModal, setScheduleModal] = useState(false);

  const load = useCallback(async () => {
    if (!spaceId) return;
    try {
      const [fl, r] = await Promise.all([
        api.listFlows(spaceId),
        api.listFlowRuns(spaceId),
      ]);
      setFlows(fl);
      setRuns(r);
    } catch (e) {
      console.error("Board load error:", e);
    }
  }, [spaceId]);

  useEffect(() => {
    load();
    if (spaceId) {
      api.getSpaceSettings(spaceId).then((s) => setMaxConcurrent(s.max_concurrent_tasks ?? 1)).catch(() => {});
    }
  }, [load, spaceId]);

  useInterval(load, 5000);

  const setView = (mode: ViewMode) => {
    setViewMode(mode);
    localStorage.setItem("board-view", mode);
  };

  const openRunDetail = (runId: string) => navigate(`/space/${spaceId}/run/${runId}`);

  const submitSchedule = async (flowId: string, oneShot: boolean) => {
    if (!spaceId) return;
    await api.scheduleFlow(spaceId, flowId, oneShot);
    load();
  };

  const stopRun = async (run: FlowRun) => {
    await api.stopRun(run.id);
    load();
  };

  const deleteRun = async (run: FlowRun) => {
    await api.deleteRun(run.id);
    load();
  };

  const toggleCollapsed = (key: string) =>
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));

  const sortedRuns = [...runs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  const runsByStatus = (key: RunStatusKey) =>
    sortedRuns.filter((r) => runStatusKey(r) === key);

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Board</h2>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setScheduleModal(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition inline-flex items-center gap-1.5"
          >
            <Play size={12} />
            New Run
          </button>
          <div className="flex items-center bg-gray-800 border border-gray-700 rounded-lg p-0.5">
            <button
              onClick={() => setView("list")}
              title="List view"
              className={`px-2.5 py-1 rounded text-xs transition-colors ${viewMode === "list" ? "bg-gray-600 text-white" : "text-gray-500 hover:text-gray-300"}`}
            >
              ☰
            </button>
            <button
              onClick={() => setView("kanban")}
              title="Kanban view"
              className={`px-2.5 py-1 rounded text-xs transition-colors ${viewMode === "kanban" ? "bg-gray-600 text-white" : "text-gray-500 hover:text-gray-300"}`}
            >
              ⊞
            </button>
          </div>
        </div>
      </div>

      {/* ── List view ─────────────────────────────────────────── */}
      {viewMode === "list" && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-gray-800 text-[10px] uppercase tracking-wide text-gray-600">
                <th className="py-2 font-medium" style={{ paddingLeft: "calc(0.75rem + 33px)", paddingRight: "0.75rem" }}>Flow</th>
                <th className="px-3 py-2 font-medium">ID</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Step</th>
                <th className="px-3 py-2 font-medium">Started</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {LIST_ORDER.map((key) => {
                const group = runsByStatus(key);
                const meta = RUN_STATUSES.find((s) => s.key === key)!;
                const isCollapsed = collapsed[key];
                return (
                  <Fragment key={key}>
                    <tr
                      className="border-b border-gray-800 bg-gray-800/40 hover:bg-gray-800/60 cursor-pointer transition-colors"
                      onClick={() => toggleCollapsed(key)}
                    >
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className={`text-[9px] transition-transform inline-block ${isCollapsed ? "" : "rotate-90"}`}>▶</span>
                          <span className={`w-2 h-2 rounded-full ${meta.dot}`} />
                          <span className="text-sm font-medium text-gray-300">{meta.label}</span>
                          <span className="text-xs text-gray-600 tabular-nums">
                            {key === "in_progress" ? `${group.length}/${maxConcurrent}` : group.length}
                          </span>
                        </div>
                      </td>
                      <td colSpan={6} />
                    </tr>
                    {!isCollapsed && (
                      group.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="px-4 py-4 text-center text-gray-700">
                            No runs
                          </td>
                        </tr>
                      ) : (
                        group.map((run) => (
                          <RunRow
                            key={run.id}
                            run={run}
                            onStop={stopRun}
                            onDelete={deleteRun}
                            onClick={openRunDetail}
                          />
                        ))
                      )
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Kanban view ───────────────────────────────────────── */}
      {viewMode === "kanban" && (
        <div className="grid grid-cols-4 gap-4 items-start">
          {KANBAN_ORDER.map((key) => {
            const group = runsByStatus(key);
            const meta = RUN_STATUSES.find((s) => s.key === key)!;
            return (
              <div key={key} className="min-w-0">
                <div className="flex items-center gap-2 mb-3 px-1">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${meta.dot}`} />
                  <span className="text-sm font-medium text-gray-300">{meta.label}</span>
                  <span className="text-xs text-gray-600 tabular-nums">
                    {key === "in_progress" ? `${group.length}/${maxConcurrent}` : group.length}
                  </span>
                </div>
                <div className="space-y-2">
                  {group.map((run) => (
                    <RunCard
                      key={run.id}
                      run={run}
                      onStop={stopRun}
                      onDelete={deleteRun}
                      onClick={openRunDetail}
                    />
                  ))}
                  {group.length === 0 && (
                    <div className="text-xs text-gray-700 text-center py-6 border border-dashed border-gray-800 rounded-xl">
                      Empty
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {scheduleModal && (
        <ScheduleModal
          flows={flows}
          onClose={() => setScheduleModal(false)}
          onSubmit={submitSchedule}
        />
      )}
    </div>
  );
}
