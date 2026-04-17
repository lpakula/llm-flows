import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import { useInterval } from "@/hooks/useInterval";
import type { Flow, Space } from "@/api/types";
import { formatCost, formatSeconds } from "@/lib/format";
import { Circle, Star, Clock } from "lucide-react";

function shortDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

export function SpaceFlowsView() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [space, setSpace] = useState<Space | null>(null);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newFlow, setNewFlow] = useState({ name: "", description: "", copy_from: "" });
  const navigate = useNavigate();
  const { reload } = useApp();

  const load = useCallback(async () => {
    if (!spaceId) return;
    const [s, f] = await Promise.all([api.getSpace(spaceId), api.listFlows(spaceId)]);
    setSpace(s);
    setFlows(f);
  }, [spaceId]);

  useEffect(() => {
    load();
  }, [load]);
  useInterval(load, 5000);

  const createFlow = async () => {
    if (!spaceId) return;
    const body: { name: string; description?: string; copy_from?: string } = {
      name: newFlow.name,
      description: newFlow.description,
    };
    if (newFlow.copy_from) body.copy_from = newFlow.copy_from;
    try {
      await api.createFlow(spaceId, body);
      setNewFlow({ name: "", description: "", copy_from: "" });
      setShowCreate(false);
      load();
      reload();
    } catch (e: unknown) {
      alert("Error: " + (e instanceof Error ? e.message : String(e)));
    }
  };


  const toggleStar = async (flowId: string, currentlyStarred: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    await api.updateFlow(flowId, { starred: !currentlyStarred });
    load();
  };

  const sortedFlows = [...flows].sort((a, b) => {
    if (a.starred && !b.starred) return -1;
    if (!a.starred && b.starred) return 1;
    return 0;
  });

  const exportFlows = async () => {
    if (!spaceId) return;
    const data = await api.exportFlows(spaceId);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${space?.name || "flows"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const importFlows = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!spaceId) return;
    const file = e.target.files?.[0];
    if (!file) return;
    const result = await api.importFlows(spaceId, file);
    alert(`Imported ${result.imported} flow(s)`);
    load();
    reload();
    e.target.value = "";
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Flows</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={exportFlows}
            className="border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white text-sm px-4 py-1.5 rounded-lg transition"
          >
            Export
          </button>
          <label className="border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white text-sm px-4 py-1.5 rounded-lg transition cursor-pointer">
            Import
            <input type="file" accept=".json" onChange={importFlows} className="hidden" />
          </label>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition"
          >
            + New Flow
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6 space-y-3">
          <input
            value={newFlow.name}
            onChange={(e) => setNewFlow({ ...newFlow, name: e.target.value })}
            placeholder="Flow name"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            autoFocus
          />
          <input
            value={newFlow.description}
            onChange={(e) => setNewFlow({ ...newFlow, description: e.target.value })}
            placeholder="Description (optional)"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <select
            value={newFlow.copy_from}
            onChange={(e) => setNewFlow({ ...newFlow, copy_from: e.target.value })}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Create from scratch</option>
            {flows.map((f) => (
              <option key={f.id} value={f.name}>
                Copy from: {f.name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <button
              onClick={createFlow}
              disabled={!newFlow.name.trim()}
              className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40"
            >
              Create
            </button>
            <button onClick={() => setShowCreate(false)} className="text-xs text-gray-500 hover:text-gray-300">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {sortedFlows.map((flow) => (
          <div
            key={flow.id}
            onClick={() => navigate(`/space/${spaceId}/flow/${flow.id}`)}
            className="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-600 transition flex flex-col cursor-pointer"
          >
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <h3 className="text-sm font-semibold text-white">{flow.name}</h3>
                <button
                  onClick={(e) => toggleStar(flow.id, !!flow.starred, e)}
                  className="shrink-0 hover:scale-110 transition-transform"
                  title={flow.starred ? "Unstar" : "Star"}
                >
                  <Star
                    size={14}
                    className={flow.starred
                      ? "text-yellow-400 fill-yellow-400"
                      : "text-gray-600 hover:text-yellow-400"
                    }
                  />
                </button>
                {(flow.active_run_count ?? 0) > 0 && (
                  <Circle size={8} className="text-yellow-400 fill-yellow-400 animate-pulse shrink-0" />
                )}
              </div>
              <span className="text-xs text-gray-500">{flow.step_count} steps</span>
            </div>
            <p className="text-xs text-gray-500 mt-1 leading-relaxed line-clamp-2 min-h-[2.5em]">
              {flow.description || "\u00A0"}
            </p>
            <div className="flex items-center gap-4 mt-auto pt-3 border-t border-gray-800 text-[10px] tabular-nums">
              <span className="text-blue-400">{flow.run_count ?? 0} runs</span>
              {flow.total_duration_seconds != null && flow.total_duration_seconds > 0 && (
                <span className="text-gray-400 flex items-center gap-0.5"><Clock size={9} className="opacity-50" />{formatSeconds(flow.total_duration_seconds)}</span>
              )}
              {(flow.total_cost_usd ?? 0) > 0 && (
                <span className="text-emerald-400">{formatCost(flow.total_cost_usd!)}</span>
              )}
              {flow.last_run_at && (
                <span className="ml-auto text-gray-500">{shortDateTime(flow.last_run_at)}</span>
              )}
            </div>
          </div>
        ))}
        {flows.length === 0 && (
          <div className="col-span-3 text-gray-500 text-center py-12">No flows</div>
        )}
      </div>
    </div>
  );
}
