import { useState, useEffect, useRef } from "react";
import { api } from "@/api/client";
import type { AgentAlias, AgentConfigEntry, ProviderInfo } from "@/api/types";

function ModelCombobox({
  value,
  onChange,
  options,
  placeholder = "Select or type a model...",
  bg = "bg-gray-900",
  disabled = false,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  placeholder?: string;
  bg?: string;
  disabled?: boolean;
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
        onFocus={() => !disabled && setOpen(true)}
        disabled={disabled}
        placeholder={placeholder}
        className={`${bg} border border-gray-700 rounded px-2 py-1 text-sm w-full focus:outline-none focus:border-gray-500 disabled:opacity-40`}
      />
      {open && !disabled && filtered.length > 0 && (
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

function InlineAliasTier({
  alias,
  agentOptions,
  modelOptions,
  isChatType,
  onSave,
}: {
  alias: AgentAlias;
  agentOptions: string[];
  modelOptions: Record<string, string[]>;
  isChatType: boolean;
  onSave: (id: string, agent: string, model: string) => void;
}) {
  const isPi = alias.type === "pi";

  const splitProviderModel = (a: string, m: string): [string, string] => {
    if (isPi) {
      const slash = m.indexOf("/");
      if (slash > 0) return [m.slice(0, slash), m.slice(slash + 1)];
      return [agentOptions[0] ?? "", m];
    }
    return [a, m];
  };

  const [resolved] = useState(() => splitProviderModel(alias.agent, alias.model));
  const [agent, setAgent] = useState(resolved[0]);
  const [model, setModel] = useState(resolved[1]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const hasOptions = agentOptions.length > 0;

  useEffect(() => {
    const [a, m] = splitProviderModel(alias.agent, alias.model);
    setAgent(a);
    setModel(m);
    setDirty(false);
  }, [alias.agent, alias.model]);

  const handleAgentChange = (v: string) => {
    setAgent(v);
    if (!isChatType) setModel("");
    setDirty(true);
  };
  const handleModelChange = (v: string) => {
    setModel(v);
    setDirty(true);
  };
  const save = async () => {
    if (!agent.trim() || !model.trim()) return;
    setSaving(true);
    if (isPi) {
      await onSave(alias.id, "pi", `${agent}/${model}`);
    } else {
      await onSave(alias.id, agent, model);
    }
    setDirty(false);
    setSaving(false);
  };

  return (
    <div className="flex items-center gap-2 flex-1 min-w-0">
      <span className="text-[10px] font-semibold text-cyan-400 uppercase tracking-wide w-12 shrink-0">{alias.name}</span>
      <select
        value={hasOptions ? agent : ""}
        onChange={(e) => handleAgentChange(e.target.value)}
        disabled={!hasOptions}
        className="bg-gray-800 border border-gray-700 rounded px-1.5 py-1 text-xs w-28 shrink-0 focus:outline-none focus:border-gray-600 disabled:opacity-40"
      >
        {!hasOptions && <option value="">—</option>}
        {agentOptions.map((a) => (
          <option key={a} value={a}>{a}</option>
        ))}
      </select>
      {isChatType ? (
        <input
          value={hasOptions ? model : ""}
          onChange={(e) => handleModelChange(e.target.value)}
          placeholder={hasOptions ? "model" : "—"}
          disabled={!hasOptions}
          className="bg-gray-800 border border-gray-700 rounded px-1.5 py-1 text-xs font-mono flex-1 min-w-0 focus:outline-none focus:border-gray-600 disabled:opacity-40"
        />
      ) : (
        <div className="flex-1 min-w-0">
          <ModelCombobox
            value={hasOptions ? model : ""}
            onChange={handleModelChange}
            options={modelOptions[agent] || []}
            placeholder={hasOptions ? "model" : "—"}
            bg="bg-gray-800"
            disabled={!hasOptions}
          />
        </div>
      )}
      {dirty && (
        <button
          onClick={save}
          disabled={saving || !agent.trim() || !model.trim()}
          className="text-[10px] px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white shrink-0"
        >
          {saving ? "..." : "Save"}
        </button>
      )}
    </div>
  );
}

function ApiKeyInput({
  agentKey,
  envVar,
  configs,
  onAdd,
  onDelete,
}: {
  agentKey: string;
  envVar: string;
  configs: AgentConfigEntry[];
  onAdd: (agent: string, key: string, value: string) => Promise<void>;
  onDelete: (agent: string, configId: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const entry = configs.find((c) => c.key === envVar);

  if (!envVar) return <span className="text-gray-600">—</span>;

  const save = async () => {
    if (!value.trim()) return;
    setSaving(true);
    await onAdd(agentKey, envVar, value.trim());
    setValue("");
    setSaving(false);
  };

  return (
    <div className="flex items-center gap-1.5">
      <input
        type="password"
        value={entry ? "••••••••" : value}
        onChange={(e) => { if (!entry) setValue(e.target.value); }}
        readOnly={!!entry}
        placeholder={envVar}
        className={`bg-gray-800 border rounded px-1.5 py-0.5 text-[11px] font-mono w-36 focus:outline-none ${entry ? "border-gray-700 text-gray-500 cursor-default" : "border-gray-700 focus:border-gray-500"}`}
        onKeyDown={(e) => e.key === "Enter" && save()}
      />
      {entry ? (
        <button
          onClick={() => onDelete(agentKey, entry.id)}
          className="text-[10px] text-gray-600 hover:text-red-400 transition-colors shrink-0"
        >
          clear
        </button>
      ) : value.trim() ? (
        <button
          onClick={save}
          disabled={saving}
          className="text-[10px] text-blue-400 hover:text-blue-300 disabled:opacity-40 shrink-0"
        >
          {saving ? "…" : "Save"}
        </button>
      ) : null}
    </div>
  );
}

export function AgentsView() {
  const [providers, setProviders] = useState<Record<string, ProviderInfo>>({});
  const [loading, setLoading] = useState(true);

  const [agentConfigs, setAgentConfigs] = useState<Record<string, AgentConfigEntry[]>>({});
  const [aliases, setAliases] = useState<AgentAlias[]>([]);
  const [models, setModels] = useState<Record<string, string[]>>({});

  const reload = async () => {
    try {
      const providersData = await api.getProvidersStatus();
      setProviders(providersData);

      const configMap: Record<string, AgentConfigEntry[]> = {};
      await Promise.all(
        Object.keys(providersData).map(async (key) => {
          try { configMap[key] = await api.getAgentConfig(key); } catch { configMap[key] = []; }
        })
      );
      setAgentConfigs(configMap);
    } catch {
      setProviders({});
    }

    try {
      const al = await api.listAgentAliases();
      setAliases(al);
      const modelMap: Record<string, string[]> = {};
      for (const k of Object.keys(await api.getProvidersStatus())) {
        try { modelMap[k] = await api.listModels(k); } catch { modelMap[k] = []; }
      }
      setModels(modelMap);
    } catch (e) {
      console.error("Failed to load aliases:", e);
    }
  };

  useEffect(() => {
    (async () => {
      await reload();
      setLoading(false);
    })();
  }, []);

  const reloadAgentConfig = async (agentName: string) => {
    try {
      const configs = await api.getAgentConfig(agentName);
      setAgentConfigs((prev) => ({ ...prev, [agentName]: configs }));
    } catch {
      setAgentConfigs((prev) => ({ ...prev, [agentName]: [] }));
    }
    setProviders(await api.getProvidersStatus());
  };

  const addConfig = async (agentName: string, key: string, value: string) => {
    await api.setAgentConfig(agentName, key, value);
    await reloadAgentConfig(agentName);
  };

  const deleteConfig = async (agentName: string, configId: string) => {
    await api.deleteAgentConfig(agentName, configId);
    await reloadAgentConfig(agentName);
  };

  const reloadAliases = async () => {
    setAliases(await api.listAgentAliases());
  };

  const saveAlias = async (id: string, agent: string, model: string) => {
    await api.updateAgentAlias(id, { agent, model });
    reloadAliases();
  };

  const tierOrder = ["mini", "normal", "max"];
  const piAliases = aliases.filter((a) => a.type === "pi").sort((a, b) => tierOrder.indexOf(a.name) - tierOrder.indexOf(b.name));
  const providerList = Object.entries(providers).map(([key, info]) => ({ key, ...info }));
  const configuredProviders = providerList.filter((p) => p.configured).map((p) => p.key);

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-10">

      {loading && <div className="text-gray-500">Loading...</div>}

      <h2 className="text-xl font-semibold mb-2">Agents</h2>
      <p className="text-xs text-gray-500 mb-6">
        Configure API keys for LLM providers. Set alias tiers to control which model each step resolves to.
      </p>

      {/* ── LLM Providers ── */}
      {!loading && (
        <section>
          <div className="border border-gray-800 rounded-xl">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/60 [&>th:first-child]:rounded-tl-xl [&>th:last-child]:rounded-tr-xl">
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide w-8"></th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">Provider</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">API Key</th>
                </tr>
              </thead>
              <tbody>
                {providerList.map((prov, i) => (
                  <tr
                    key={prov.key}
                    className={`bg-gray-900 hover:bg-gray-800/50 transition-colors ${i < providerList.length - 1 ? "border-b border-gray-800" : ""}`}
                  >
                    <td className="px-4 py-2.5">
                      <span className={`inline-block w-2 h-2 rounded-full ${prov.configured ? "bg-green-400" : "bg-gray-600"}`} />
                    </td>
                    <td className="px-4 py-2.5 font-medium text-white">{prov.label}</td>
                    <td className="px-4 py-2.5">
                      <ApiKeyInput
                        agentKey={prov.key}
                        envVar={prov.api_key_env}
                        configs={agentConfigs[prov.key] || []}
                        onAdd={addConfig}
                        onDelete={deleteConfig}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
              {piAliases.length > 0 && (
                <tfoot>
                  <tr className="border-t border-gray-700 bg-gray-900/80 [&>td:first-child]:rounded-bl-xl [&>td:last-child]:rounded-br-xl">
                    <td colSpan={3} className="px-4 py-3">
                      <div className="flex items-center gap-6">
                        <span className="text-[10px] font-medium text-gray-500 uppercase tracking-wide shrink-0">Tiers</span>
                        <div className="flex gap-6 flex-1 min-w-0">
                          {piAliases.map((a) => (
                            <InlineAliasTier
                              key={a.id}
                              alias={a}
                              agentOptions={configuredProviders}
                              modelOptions={models}
                              isChatType={false}
                              onSave={saveAlias}
                            />
                          ))}
                        </div>
                      </div>
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </section>
      )}

    </div>
  );
}
