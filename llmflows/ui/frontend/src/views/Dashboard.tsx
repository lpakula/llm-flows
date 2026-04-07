import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { DashboardEntry } from "@/api/types";
import { statusBadge } from "@/lib/format";

export function Dashboard() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<DashboardEntry[] | null>(null);
  const navigate = useNavigate();

  const refresh = async () => {
    try {
      setData(await api.getDashboard());
    } catch (e) {
      console.error("Dashboard load error:", e);
    }
    setLoading(false);
  };

  useEffect(() => {
    refresh();
  }, []);
  useInterval(refresh, 8000);

  const totalTasks = (entry: DashboardEntry) =>
    Object.values(entry.task_counts).reduce((a, b) => a + b, 0);

  const stepLabel = (step: string | null) => {
    if (!step) return "-";
    if (step === "__one_shot__") return "one-shot";
    if (step === "__summary__") return "summary";
    return step;
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-6">Dashboard</h2>

      {loading && <div className="text-gray-500">Loading...</div>}

      {data && data.length > 0 && (
        <div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {data.map((entry) => (
              <div
                key={entry.project.id}
                onClick={() => navigate(`/project/${entry.project.id}`)}
                className="bg-gray-900 border border-gray-800 rounded-xl p-4 cursor-pointer hover:border-gray-600 transition"
              >
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-medium text-white">{entry.project.name}</h3>
                  <span className="text-xs text-gray-500">{totalTasks(entry)} tasks</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  {entry.queue_depth > 0 && (
                    <span className="text-blue-400">{entry.queue_depth} queued</span>
                  )}
                  {entry.active_runs > 0 && (
                    <span className="text-yellow-400">{entry.active_runs} running</span>
                  )}
                </div>
                {entry.executing.map((run) => (
                  <div key={run.run.id} className="mt-2 bg-gray-800 rounded-lg px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-1.5 h-1.5 rounded-full animate-pulse ${
                          run.agent_active ? "bg-green-400" : "bg-yellow-400"
                        }`}
                      />
                      <span className="text-gray-300">{run.run.flow_name}</span>
                      <span className="text-gray-500">step:</span>
                      <span className="text-cyan-400">{stepLabel(run.run.current_step)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>

          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
            Recent Completions
          </h3>
          <div className="space-y-2">
            {data.flatMap((entry) =>
              entry.recent_completions.map((run) => (
                <div
                  key={run.id}
                  className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 flex items-center gap-4"
                >
                  <span className="text-xs font-mono text-gray-400">{run.id}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${statusBadge(run.outcome || "completed")}`}>
                    {run.outcome || "completed"}
                  </span>
                  <span className="text-xs text-cyan-400">{run.flow_name}</span>
                  <span className="text-xs text-gray-500 flex-1 truncate">{run.summary || "-"}</span>
                </div>
              )),
            )}
          </div>
        </div>
      )}

      {!loading && (!data || data.length === 0) && (
        <div className="text-gray-500 text-center py-12">
          No projects registered. Run <code className="text-cyan-400">llmflows register</code> in a git repo.
        </div>
      )}
    </div>
  );
}
