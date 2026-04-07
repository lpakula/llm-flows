import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import type { Flow } from "@/api/types";

export function FlowsView() {
  const [flows, setFlows] = useState<Flow[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newFlow, setNewFlow] = useState({ name: "", description: "", copy_from: "" });
  const navigate = useNavigate();
  const { reload } = useApp();

  const load = async () => {
    setFlows(await api.listFlows());
  };

  useEffect(() => {
    load();
  }, []);

  const createFlow = async () => {
    const body: { name: string; description?: string; copy_from?: string } = {
      name: newFlow.name,
      description: newFlow.description,
    };
    if (newFlow.copy_from) body.copy_from = newFlow.copy_from;
    try {
      await api.createFlow(body);
      setNewFlow({ name: "", description: "", copy_from: "" });
      setShowCreate(false);
      load();
      reload();
    } catch (e: unknown) {
      alert("Error: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const deleteFlow = async (flowId: string) => {
    if (!confirm("Delete this flow?")) return;
    try {
      await api.deleteFlow(flowId);
      load();
      reload();
    } catch (e: unknown) {
      alert("Error: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const exportFlows = async () => {
    const data = await api.exportFlows();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "flows.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const importFlows = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const result = await api.importFlows(file);
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
          <button onClick={exportFlows} className="text-xs text-gray-500 hover:text-gray-300 transition">
            Export
          </button>
          <label className="text-xs text-gray-500 hover:text-gray-300 transition cursor-pointer">
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

      {/* Create Form */}
      {showCreate && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-4 space-y-3">
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
            <button onClick={createFlow} disabled={!newFlow.name.trim()} className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40">
              Create
            </button>
            <button onClick={() => setShowCreate(false)} className="text-xs text-gray-500 hover:text-gray-300">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Flow List */}
      <div className="space-y-2">
        {flows.map((flow) => (
          <div
            key={flow.id}
            className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-3 flex items-center justify-between hover:border-gray-600 transition"
          >
            <div className="flex items-center gap-3 cursor-pointer" onClick={() => navigate(`/flow-editor/${flow.id}`)}>
              <h3 className="text-sm font-medium text-white">{flow.name}</h3>
              <span className="text-xs text-gray-500">{flow.step_count} steps</span>
              {flow.description && <span className="text-xs text-gray-600 truncate max-w-xs">{flow.description}</span>}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => navigate(`/flow-editor/${flow.id}`)}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                Edit
              </button>
              <button
                onClick={() => deleteFlow(flow.id)}
                className="text-xs text-gray-600 hover:text-red-400"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
        {flows.length === 0 && <div className="text-gray-500 text-center py-8">No flows</div>}
      </div>
    </div>
  );
}
