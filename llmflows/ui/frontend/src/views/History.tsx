import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { useLogStream } from "@/hooks/useEventSource";
import { LogViewer } from "@/components/LogViewer";
import type { TaskRun, StepRunInfo } from "@/api/types";
import { statusBadge, displayStatus, statusDot, duration, stepBoxClass, stepConnectorClass } from "@/lib/format";

export function HistoryView() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [filterStatus, setFilterStatus] = useState("");
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [runSteps, setRunSteps] = useState<Record<string, StepRunInfo[]>>({});
  const [logUrl, setLogUrl] = useState<string | null>(null);
  const limit = 50;

  const { entries: logEntries, streaming } = useLogStream(logUrl);

  const load = useCallback(async () => {
    try {
      setLoading(runs.length === 0);
      const data = await api.getHistory(limit, offset);
      setRuns(data.runs);
      setTotal(data.total);
    } catch (e) {
      console.error("History load error:", e);
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => {
    load();
  }, [load]);
  useInterval(load, 5000);

  const filteredRuns = filterStatus
    ? runs.filter((r) => {
        if (filterStatus === "running") return r.status === "running";
        if (filterStatus === "queued") return r.status === "queued";
        if (filterStatus === "completed") return r.status === "completed" && (!r.outcome || r.outcome === "completed");
        if (filterStatus === "failed") return r.status === "completed" && r.outcome === "failed";
        if (filterStatus === "cancelled") return r.status === "completed" && r.outcome === "cancelled";
        if (filterStatus === "timeout") return r.status === "completed" && r.outcome === "timeout";
        return true;
      })
    : runs;

  const loadRunSteps = async (runId: string) => {
    try {
      const data = await api.getRunSteps(runId);
      setRunSteps((prev) => ({ ...prev, [runId]: data.steps }));
    } catch {
      setRunSteps((prev) => ({ ...prev, [runId]: [] }));
    }
  };

  const toggleRun = (runId: string) => {
    if (expandedRun === runId) {
      setExpandedRun(null);
      setLogUrl(null);
    } else {
      setExpandedRun(runId);
      loadRunSteps(runId);
    }
  };

  const viewRunLogs = (runId: string) => {
    const run = runs.find((r) => r.id === runId);
    if (run?.log_path === "inline") {
      setLogUrl(null);
      return;
    }
    setLogUrl(`/api/runs/${runId}/logs`);
    setExpandedRun(runId);
  };

  const viewStepLogs = (step: StepRunInfo) => {
    if (!step.step_run) return;
    setLogUrl(`/api/step-runs/${step.step_run.id}/logs`);
  };

  const pageInfo = `${offset + 1}\u2013${Math.min(offset + limit, total)} of ${total}`;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Run History</h2>
        <div className="flex items-center gap-3">
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs"
          >
            <option value="">All statuses</option>
            <option value="running">Running</option>
            <option value="queued">Queued</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="timeout">Timeout</option>
          </select>
        </div>
      </div>

      {loading && <div className="text-gray-500">Loading...</div>}

      <div className="space-y-2">
        {filteredRuns.map((run) => (
          <div key={run.id} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div
              className="px-5 py-3 flex items-center gap-4 cursor-pointer hover:bg-gray-800/50"
              onClick={() => toggleRun(run.id)}
            >
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot(run.status, run.outcome)}`} />
              <span className={`text-xs px-2 py-0.5 rounded ${statusBadge(displayStatus(run))}`}>
                {displayStatus(run)}
              </span>
              <span className="text-xs text-cyan-400">{run.flow_name}</span>
              <span className="text-xs text-gray-500 truncate">{run.task_name || run.task_id}</span>
              <span className="text-xs text-gray-600 truncate">{run.project_name || ""}</span>
              <span className="text-xs text-gray-500 ml-auto flex-shrink-0">
                {duration(run.started_at, run.completed_at)}
              </span>
              <span className="text-xs text-gray-600">{expandedRun === run.id ? "▲" : "▼"}</span>
            </div>

            {expandedRun === run.id && (
              <div className="border-t border-gray-800">
                <div className="px-5 py-2 flex items-center gap-3">
                  <button
                    onClick={() => run.task_id && navigate(`/task/${run.task_id}`)}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    View Task
                  </button>
                  <button
                    onClick={() => run.project_id && navigate(`/project/${run.project_id}`)}
                    className="text-xs text-gray-500 hover:text-gray-300"
                  >
                    View Project
                  </button>
                  <button onClick={() => viewRunLogs(run.id)} className="text-xs text-gray-500 hover:text-gray-300">
                    View Logs
                  </button>
                </div>

                {/* Step pipeline */}
                {(runSteps[run.id] || []).length > 0 && (
                  <div className="px-5 py-2 flex items-center gap-1 overflow-x-auto border-t border-gray-800">
                    {(runSteps[run.id] || []).map((step, i) => (
                      <div key={i} className="flex items-center gap-1">
                        {i > 0 && <div className={`w-4 h-0.5 ${stepConnectorClass(step.status)}`} />}
                        <button
                          onClick={() => step.step_run && viewStepLogs(step)}
                          className={`px-2 py-1 rounded border text-[11px] whitespace-nowrap ${stepBoxClass(step.status)} ${
                            step.step_run ? "cursor-pointer hover:opacity-80" : "cursor-default"
                          }`}
                        >
                          {step.name === "__one_shot__" ? "one-shot" : step.name === "__summary__" ? "summary" : step.name}
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {logUrl && (
                  <div className="h-80 border-t border-gray-800">
                    <LogViewer entries={logEntries} streaming={streaming} />
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Pagination */}
      {total > limit && (
        <div className="flex items-center justify-between mt-4 text-xs text-gray-500">
          <span>{pageInfo}</span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset === 0}
              className="px-3 py-1 border border-gray-700 rounded disabled:opacity-30"
            >
              Prev
            </button>
            <button
              onClick={() => setOffset(offset + limit)}
              disabled={offset + limit >= total}
              className="px-3 py-1 border border-gray-700 rounded disabled:opacity-30"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
