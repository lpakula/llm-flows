import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { DashboardEntry } from "@/api/types";

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

  const stepLabel = (step: string | null) => {
    if (!step) return "-";
    if (step === "__post_run__") return "post-run analysis";
    return step;
  };

  const shortPath = (path: string) => path.replace(/^\/Users\/[^/]+/, "~");

  const isActive = (entry: DashboardEntry) =>
    entry.active_runs > 0 || entry.queue_depth > 0;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-1">Dashboard</h2>
        <p className="text-sm text-gray-500">
          To add a space, run{" "}
          <code className="text-cyan-400 bg-gray-800 px-1.5 py-0.5 rounded text-xs">llmflows register</code>{" "}
          in any folder.
        </p>
      </div>

      {loading && <div className="text-gray-500">Loading...</div>}

      {data && data.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.map((entry) => (
            <div
              key={entry.space.id}
              onClick={() => navigate(`/space/${entry.space.id}`)}
              className="group bg-gray-900 border border-gray-800 rounded-xl cursor-pointer hover:border-gray-600 hover:bg-gray-800/60 transition-all duration-150 overflow-hidden"
            >
              {/* Card header */}
              <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="font-semibold text-white truncate">{entry.space.name}</h3>
                  <p className="text-xs text-gray-500 font-mono mt-0.5 truncate">{shortPath(entry.space.path)}</p>
                </div>
                {isActive(entry) ? (
                  <span className="flex items-center gap-1.5 text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded-full px-2 py-0.5 flex-shrink-0">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                    active
                  </span>
                ) : (
                  <span className="text-xs text-gray-600 bg-gray-800 border border-gray-700 rounded-full px-2 py-0.5 flex-shrink-0">
                    idle
                  </span>
                )}
              </div>

              {/* Stats row */}
              <div className="px-4 pb-3 flex items-center gap-3">
                {entry.run_counts.running > 0 && (
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
                    <span className="text-xs text-yellow-400">{entry.run_counts.running} running</span>
                  </div>
                )}
                {entry.run_counts.queued > 0 && (
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                    <span className="text-xs text-blue-400">{entry.run_counts.queued} queued</span>
                  </div>
                )}
                {entry.run_counts.running === 0 && entry.run_counts.queued === 0 && (
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-600" />
                    <span className="text-xs text-gray-500">idle</span>
                  </div>
                )}
              </div>

              {/* Live runs */}
              {entry.executing.length > 0 && (
                <div className="border-t border-gray-800 px-4 py-2.5 space-y-1.5">
                  {entry.executing.map((run) => (
                    <div key={run.run.id} className="flex items-center gap-2 text-xs">
                      <span
                        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 animate-pulse ${
                          run.agent_active ? "bg-green-400" : "bg-yellow-400"
                        }`}
                      />
                      <span className="text-gray-300 truncate flex-1">{run.run.flow_name ?? "run"}</span>
                      <span className="text-gray-600">→</span>
                      <span className="text-cyan-400 flex-shrink-0">{stepLabel(run.run.current_step)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!loading && (!data || data.length === 0) && (
        <div className="text-gray-500 text-center py-12">
          <p>No spaces registered. Run <code className="text-cyan-400">llmflows register</code> in any folder.</p>
          <p className="mt-2 text-gray-600 text-sm">Flows and skills will be imported automatically from the space folder.</p>
        </div>
      )}
    </div>
  );
}
