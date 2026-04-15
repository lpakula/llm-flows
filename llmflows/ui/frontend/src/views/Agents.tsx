import { useState, useEffect, useRef } from "react";
import { api } from "@/api/client";
import type { AgentInfo, AgentAlias, AgentConfigEntry } from "@/api/types";

function ModelCombobox({
  value,
  onChange,
  options,
  placeholder = "Select or type a model...",
  bg = "bg-gray-900",
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  placeholder?: string;
  bg?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(value);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { setQuery(value); }, [value]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = query
    ? options.filter((o) => o.toLowerCase().includes(query.toLowerCase()))
    : options;

  const commit = (v: string) => {
    onChange(v);
    setQuery(v);
    setOpen(false);
  };

  return (
    <div ref={ref} className="relative w-full">
      <input
        value={query}
        onChange={(e) => { setQuery(e.target.value); onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        className={`${bg} border border-gray-700 rounded px-2 py-1 text-sm w-full focus:outline-none focus:border-gray-500`}
      />
      {open && filtered.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full max-h-48 overflow-y-auto bg-gray-800 border border-gray-700 rounded shadow-lg">
          {filtered.map((m) => (
            <li
              key={m}
              onMouseDown={() => commit(m)}
              className={`px-3 py-1.5 text-xs font-mono cursor-pointer hover:bg-gray-700 ${m === value ? "text-cyan-400" : "text-gray-300"}`}
            >
              {m}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AgentsView() {
  const [agents, setAgents] = useState<Record<string, AgentInfo>>({});
  const [loading, setLoading] = useState(true);

  const [agentConfigs, setAgentConfigs] = useState<Record<string, AgentConfigEntry[]>>({});
  const [addingEnvFor, setAddingEnvFor] = useState<string | null>(null);
  const [newConfigKey, setNewConfigKey] = useState("");
  const [newConfigValue, setNewConfigValue] = useState("");

  const [aliases, setAliases] = useState<AgentAlias[]>([]);
  const [editingAlias, setEditingAlias] = useState<string | null>(null);
  const [aliasForm, setAliasForm] = useState({ name: "", agent: "", model: "" });
  const [agentNames, setAgentNames] = useState<string[]>([]);
  const [models, setModels] = useState<Record<string, string[]>>({});


  useEffect(() => {
    (async () => {
      try {
        const agentsData = await api.getAgentsStatus();
        setAgents(agentsData);

        // Load all agent configs upfront
        const configMap: Record<string, AgentConfigEntry[]> = {};
        await Promise.all(
          Object.keys(agentsData).map(async (key) => {
            try {
              configMap[key] = await api.getAgentConfig(key);
            } catch {
              configMap[key] = [];
            }
          })
        );
        setAgentConfigs(configMap);
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

  const reloadAgentConfig = async (agentName: string) => {
    try {
      const configs = await api.getAgentConfig(agentName);
      setAgentConfigs((prev) => ({ ...prev, [agentName]: configs }));
    } catch {
      setAgentConfigs((prev) => ({ ...prev, [agentName]: [] }));
    }
  };

  const addConfig = async (agentName: string) => {
    if (!newConfigKey.trim()) return;
    await api.setAgentConfig(agentName, newConfigKey.trim(), newConfigValue);
    await reloadAgentConfig(agentName);
    setNewConfigKey("");
    setNewConfigValue("");
    setAddingEnvFor(null);
  };

  const deleteConfig = async (agentName: string, configId: string) => {
    await api.deleteAgentConfig(agentName, configId);
    await reloadAgentConfig(agentName);
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


  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-6">Agents</h2>

      {loading && <div className="text-gray-500">Loading...</div>}

      {/* Agents table */}
      {!loading && (
        <div className="mb-10">
          <div className="border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/60">
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide w-8"></th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Agent</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Binary</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Path</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Env Variables</th>
                </tr>
              </thead>
              <tbody>
                {agentList.map((agent, i) => {
                  const configs = agentConfigs[agent.key] || [];
                  const isAddingEnv = addingEnvFor === agent.key;
                  return (
                    <>
                      <tr
                        key={agent.key}
                        className={`${i < agentList.length - 1 || isAddingEnv ? "border-b border-gray-800" : ""} bg-gray-900 hover:bg-gray-800/50 transition-colors`}
                      >
                        <td className="px-4 py-3">
                          <span
                            className={`inline-block w-2 h-2 rounded-full ${agent.available ? "bg-green-400" : "bg-gray-600"}`}
                          />
                        </td>
                        <td className="px-4 py-3 font-medium text-white">{agent.label}</td>
                        <td className="px-4 py-3 font-mono text-gray-400">{agent.binary}</td>
                        <td className="px-4 py-3">
                          <span className={agent.available ? "text-green-400" : "text-gray-500"}>
                            {agent.available ? "Available" : "Not found"}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-500 text-xs max-w-[220px] truncate">
                          {agent.binary_path ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2 flex-wrap">
                            {configs.map((c) => (
                              <span
                                key={c.id}
                                className="group inline-flex items-center gap-1 bg-gray-800 border border-gray-700 rounded px-2 py-0.5 font-mono text-xs text-gray-300"
                              >
                                {c.key}
                                <button
                                  onClick={() => deleteConfig(agent.key, c.id)}
                                  className="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity leading-none"
                                >
                                  ×
                                </button>
                              </span>
                            ))}
                            <button
                              onClick={() => {
                                setAddingEnvFor(isAddingEnv ? null : agent.key);
                                setNewConfigKey("");
                                setNewConfigValue("");
                              }}
                              className="text-gray-600 hover:text-blue-400 text-xs transition-colors"
                              title="Add env variable"
                            >
                              + Add
                            </button>
                          </div>
                        </td>
                      </tr>
                      {isAddingEnv && (
                        <tr key={`${agent.key}-add-env`} className={`bg-gray-900/80 ${i < agentList.length - 1 ? "border-b border-gray-800" : ""}`}>
                          <td colSpan={6} className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <input
                                value={newConfigKey}
                                onChange={(e) => setNewConfigKey(e.target.value)}
                                placeholder="KEY"
                                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono w-36 focus:outline-none focus:border-gray-500"
                                autoFocus
                                onKeyDown={(e) => e.key === "Enter" && addConfig(agent.key)}
                              />
                              <input
                                value={newConfigValue}
                                onChange={(e) => setNewConfigValue(e.target.value)}
                                placeholder="value"
                                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono w-52 focus:outline-none focus:border-gray-500"
                                onKeyDown={(e) => e.key === "Enter" && addConfig(agent.key)}
                              />
                              <button
                                onClick={() => addConfig(agent.key)}
                                disabled={!newConfigKey.trim()}
                                className="text-xs text-blue-400 disabled:opacity-40 hover:text-blue-300 transition-colors"
                              >
                                Add
                              </button>
                              <button
                                onClick={() => setAddingEnvFor(null)}
                                className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                              >
                                Cancel
                              </button>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
                {agentList.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-gray-500 bg-gray-900">
                      No agents configured
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Aliases table */}
      {!loading && (
        <div>
          <div className="mb-3">
            <h3 className="text-base font-semibold">Aliases</h3>
            <p className="text-xs text-gray-500 mt-0.5">Agent/model combinations referenced by flow steps</p>
          </div>

          <div className="border border-gray-800 rounded-xl overflow-visible">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/60">
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Name</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Agent</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Model</th>
                  <th className="px-4 py-3 w-24"></th>
                </tr>
              </thead>
              <tbody>
                {aliases.map((a, i) => (
                  <tr
                    key={a.id}
                    className={`bg-gray-900 hover:bg-gray-800/50 transition-colors ${i < aliases.length - 1 ? "border-b border-gray-800" : ""}`}
                  >
                    {editingAlias === a.id ? (
                      <>
                        <td className="px-4 py-2 font-medium text-cyan-400">{a.name}</td>
                        <td className="px-4 py-2">
                          <select
                            value={aliasForm.agent}
                            onChange={(e) => setAliasForm({ ...aliasForm, agent: e.target.value, model: "" })}
                            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-full focus:outline-none"
                          >
                            {agentNames.map((ag) => (
                              <option key={ag} value={ag}>{ag}</option>
                            ))}
                          </select>
                        </td>
                        <td className="px-4 py-2">
                          <ModelCombobox
                            value={aliasForm.model}
                            onChange={(v) => setAliasForm({ ...aliasForm, model: v })}
                            options={models[aliasForm.agent] || []}
                            bg="bg-gray-800"
                          />
                        </td>
                        <td className="px-4 py-2">
                          <div className="flex items-center gap-2">
                            <button onClick={() => saveAlias(a.id)} disabled={!aliasForm.agent.trim() || !aliasForm.model.trim()} className="text-xs text-blue-400 disabled:opacity-40 hover:text-blue-300 transition-colors">Save</button>
                            <button onClick={() => setEditingAlias(null)} className="text-xs text-gray-500 hover:text-gray-300 transition-colors">Cancel</button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-3 font-medium text-cyan-400">{a.name}</td>
                        <td className="px-4 py-3 text-gray-400">{a.agent}</td>
                        <td className="px-4 py-3 text-gray-500 font-mono text-xs">{a.model}</td>
                        <td className="px-4 py-3 text-right">
                          <button onClick={() => startEditAlias(a)} className="text-xs text-gray-500 hover:text-blue-400 transition-colors">Edit</button>
                        </td>
                      </>
                    )}
                  </tr>
                ))}

                {aliases.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-gray-500 bg-gray-900">
                      No aliases defined
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  );
}
