import { useState, useEffect } from "react";
import { api } from "@/api/client";
import type { AgentInfo } from "@/api/types";

export function AgentsView() {
  const [agents, setAgents] = useState<Record<string, AgentInfo>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setAgents(await api.getAgentsStatus());
      } catch {
        setAgents({});
      }
      setLoading(false);
    })();
  }, []);

  const agentList = Object.entries(agents).map(([key, info]) => ({ key, ...info }));

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-6">Agents</h2>

      {loading && <div className="text-gray-500">Loading...</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {agentList.map((agent) => (
          <div
            key={agent.key}
            className={`bg-gray-900 border rounded-xl p-5 ${
              agent.available ? "border-green-800" : "border-gray-800"
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-white">{agent.label}</h3>
              <span
                className={`w-2.5 h-2.5 rounded-full ${agent.available ? "bg-green-400" : "bg-gray-600"}`}
              />
            </div>
            <div className="space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-500">Binary</span>
                <span className="text-gray-400 font-mono">{agent.binary}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Status</span>
                <span className={agent.available ? "text-green-400" : "text-gray-600"}>
                  {agent.available ? "Available" : "Not found"}
                </span>
              </div>
              {agent.binary_path && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Path</span>
                  <span className="text-gray-500 font-mono truncate max-w-[200px]">{agent.binary_path}</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {!loading && agentList.length === 0 && (
        <div className="text-gray-500 text-center py-8">No agents configured</div>
      )}
    </div>
  );
}
