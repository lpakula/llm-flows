import { useState, useEffect } from "react";
import { api } from "@/api/client";
import type { AgentInfo, AgentAlias, AgentConfigEntry } from "@/api/types";

export function AgentsView() {
  const [agents, setAgents] = useState<Record<string, AgentInfo>>({});
  const [loading, setLoading] = useState(true);

  // Per-agent config
  const [agentConfigs, setAgentConfigs] = useState<Record<string, AgentConfigEntry[]>>({});
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [newConfigKey, setNewConfigKey] = useState("");
  const [newConfigValue, setNewConfigValue] = useState("");

  // Agent aliases
  const [aliases, setAliases] = useState<AgentAlias[]>([]);
  const [editingAlias, setEditingAlias] = useState<string | null>(null);
  const [aliasForm, setAliasForm] = useState({ name: "", agent: "", model: "" });
  const [showAddAlias, setShowAddAlias] = useState(false);
  const [newAlias, setNewAlias] = useState({ name: "", agent: "cursor", model: "" });
  const [agentNames, setAgentNames] = useState<string[]>([]);
  const [models, setModels] = useState<Record<string, string[]>>({});

  useEffect(() => {
    (async () => {
      try {
        setAgents(await api.getAgentsStatus());
      } catch {
        setAgents({});
      }

      try {
        const [al, ag] = await Promise.all([
          api.listAgentAliases(),
          api.listAgents(),
        ]);
        setAliases(al);
        setAgentNames(ag);
        const modelMap: Record<string, string[]> = {};
        for (const a of ag) {
          modelMap[a] = await api.listModels(a);
        }
        setModels(modelMap);
      } catch (e) {
        console.error("Failed to load aliases:", e);
      }

      setLoading(false);
    })();
  }, []);

  const agentList = Object.entries(agents).map(([key, info]) => ({ key, ...info }));

  const loadAgentConfig = async (agentName: string) => {
    try {
      const configs = await api.getAgentConfig(agentName);
      setAgentConfigs((prev) => ({ ...prev, [agentName]: configs }));
    } catch {
      setAgentConfigs((prev) => ({ ...prev, [agentName]: [] }));
    }
  };

  const toggleAgentConfig = (agentName: string) => {
    if (expandedAgent === agentName) {
      setExpandedAgent(null);
    } else {
      setExpandedAgent(agentName);
      loadAgentConfig(agentName);
    }
    setNewConfigKey("");
    setNewConfigValue("");
  };

  const addConfig = async (agentName: string) => {
    if (!newConfigKey.trim()) return;
    const configs = await api.setAgentConfig(agentName, newConfigKey.trim(), newConfigValue);
    setAgentConfigs((prev) => ({ ...prev, [agentName]: configs }));
    setNewConfigKey("");
    setNewConfigValue("");
  };

  const deleteConfig = async (agentName: string, configId: string) => {
    await api.deleteAgentConfig(agentName, configId);
    loadAgentConfig(agentName);
  };

  const reloadAliases = async () => {
    setAliases(await api.listAgentAliases());
  };

  const startEditAlias = (a: AgentAlias) => {
    setEditingAlias(a.id);
    setAliasForm({ name: a.name, agent: a.agent, model: a.model });
  };

  const saveAlias = async (id: string) => {
    await api.updateAgentAlias(id, aliasForm);
    setEditingAlias(null);
    reloadAliases();
  };

  const addAlias = async () => {
    if (!newAlias.name.trim() || !newAlias.model.trim()) return;
    await api.createAgentAlias(newAlias);
    setNewAlias({ name: "", agent: "cursor", model: "" });
    setShowAddAlias(false);
    reloadAliases();
  };

  const deleteAlias = async (id: string) => {
    if (!confirm("Delete this alias?")) return;
    await api.deleteAgentAlias(id);
    reloadAliases();
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-6">Agents</h2>

      {loading && <div className="text-gray-500">Loading...</div>}

      {/* Agent availability */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
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
            <button
              onClick={() => toggleAgentConfig(agent.key)}
              className="mt-3 text-[11px] text-gray-500 hover:text-gray-300 transition"
            >
              {expandedAgent === agent.key ? "Hide env" : `Env${(agentConfigs[agent.key] || []).length ? ` (${agentConfigs[agent.key].length})` : ""}`}
            </button>
            {expandedAgent === agent.key && (
              <div className="mt-2 pt-2 border-t border-gray-800 space-y-2">
                {(agentConfigs[agent.key] || []).map((c) => (
                  <div key={c.id} className="flex items-center gap-2 text-xs">
                    <span className="text-gray-400 font-mono">{c.key}</span>
                    <span className="text-gray-600">=</span>
                    <span className="text-gray-500 font-mono truncate flex-1">{c.value ? "••••••••" : "(empty)"}</span>
                    <button onClick={() => deleteConfig(agent.key, c.id)} className="text-gray-600 hover:text-red-400">×</button>
                  </div>
                ))}
                <div className="flex gap-1">
                  <input
                    value={newConfigKey}
                    onChange={(e) => setNewConfigKey(e.target.value)}
                    placeholder="KEY"
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono w-28"
                  />
                  <input
                    value={newConfigValue}
                    onChange={(e) => setNewConfigValue(e.target.value)}
                    placeholder="value"
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono flex-1"
                  />
                  <button
                    onClick={() => addConfig(agent.key)}
                    disabled={!newConfigKey.trim()}
                    className="text-xs text-blue-400 disabled:opacity-40 px-1"
                  >
                    Add
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {!loading && agentList.length === 0 && (
        <div className="text-gray-500 text-center py-8 mb-8">No agents configured</div>
      )}

      {/* Agent Aliases */}
      {!loading && (
        <div className="max-w-2xl">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium">Aliases</h3>
              <button
                onClick={() => setShowAddAlias(true)}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                + Add Alias
              </button>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              Define agent/model combinations. Each flow step references an alias by name.
            </p>

            {showAddAlias && (
              <div className="mb-4 p-3 bg-gray-800 rounded-lg space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <input
                    value={newAlias.name}
                    onChange={(e) => setNewAlias({ ...newAlias, name: e.target.value })}
                    placeholder="Alias name"
                    className="bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm"
                    autoFocus
                  />
                  <select
                    value={newAlias.agent}
                    onChange={(e) => setNewAlias({ ...newAlias, agent: e.target.value, model: "" })}
                    className="bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm"
                  >
                    {agentNames.map((a) => (
                      <option key={a} value={a}>{a}</option>
                    ))}
                  </select>
                  <select
                    value={newAlias.model}
                    onChange={(e) => setNewAlias({ ...newAlias, model: e.target.value })}
                    className="bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm col-span-2"
                  >
                    <option value="">Select model...</option>
                    {(models[newAlias.agent] || []).map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2">
                  <button onClick={addAlias} disabled={!newAlias.name.trim() || !newAlias.model} className="text-xs text-blue-400 disabled:opacity-40">
                    Add
                  </button>
                  <button onClick={() => setShowAddAlias(false)} className="text-xs text-gray-500">Cancel</button>
                </div>
              </div>
            )}

            <div className="space-y-1">
              {aliases.map((a) => (
                <div key={a.id} className="border border-gray-800 rounded-lg px-4 py-2">
                  {editingAlias === a.id ? (
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          value={aliasForm.name}
                          onChange={(e) => setAliasForm({ ...aliasForm, name: e.target.value })}
                          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm"
                        />
                        <select
                          value={aliasForm.agent}
                          onChange={(e) => setAliasForm({ ...aliasForm, agent: e.target.value, model: "" })}
                          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm"
                        >
                          {agentNames.map((ag) => (
                            <option key={ag} value={ag}>{ag}</option>
                          ))}
                        </select>
                        <select
                          value={aliasForm.model}
                          onChange={(e) => setAliasForm({ ...aliasForm, model: e.target.value })}
                          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm col-span-2"
                        >
                          <option value="">Select model...</option>
                          {(models[aliasForm.agent] || []).map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      </div>
                      <div className="flex gap-2">
                        <button onClick={() => saveAlias(a.id)} className="text-xs text-blue-400">Save</button>
                        <button onClick={() => setEditingAlias(null)} className="text-xs text-gray-500">Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-medium text-cyan-400 w-20">{a.name}</span>
                        <span className="text-xs text-gray-400">{a.agent}</span>
                        <span className="text-xs text-gray-500">{a.model}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <button onClick={() => startEditAlias(a)} className="text-xs text-gray-500 hover:text-blue-400">Edit</button>
                        <button onClick={() => deleteAlias(a.id)} className="text-xs text-gray-600 hover:text-red-400">Delete</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
