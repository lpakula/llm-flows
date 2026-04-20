import { useState, useEffect } from "react";
import { api } from "@/api/client";
import type { ProviderInfo, AgentConfigEntry } from "@/api/types";
import { Bot, Wrench, CheckCircle2, ChevronRight, ChevronDown } from "lucide-react";

export function WelcomeView({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(1);
  const [providers, setProviders] = useState<Record<string, ProviderInfo>>({});
  const [configs, setConfigs] = useState<Record<string, AgentConfigEntry[]>>({});
  const [loading, setLoading] = useState(true);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [keyValue, setKeyValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const prov = await api.getProvidersStatus();
      setProviders(prov);

      const configMap: Record<string, AgentConfigEntry[]> = {};
      await Promise.all(
        Object.keys(prov).map(async (key) => {
          try { configMap[key] = await api.getAgentConfig(key); } catch { configMap[key] = []; }
        })
      );
      setConfigs(configMap);
    } catch (e) {
      console.error("Failed to load setup data:", e);
    }
    setLoading(false);
  };

  useEffect(() => { reload(); }, []);

  const providerList = Object.entries(providers).map(([key, info]) => ({ key, ...info }));
  const configuredProviders = providerList.filter((p) => p.configured);
  const hasAnyKey = configuredProviders.length > 0;

  const selected = selectedProvider ? providerList.find((p) => p.key === selectedProvider) : null;
  const selectedConfigured = selected ? selected.configured : false;
  const selectedEntry = selected ? (configs[selected.key] || []).find((c) => c.key === selected.api_key_env) : null;

  const saveKey = async () => {
    if (!selected || !keyValue.trim()) return;
    setKeyError(null);
    setValidating(true);
    try {
      const result = await api.validateAgentKey(selected.key, keyValue.trim());
      if (!result.valid) {
        setKeyError(result.error || "Invalid API key");
        setValidating(false);
        return;
      }
    } catch {
      setKeyError("Could not validate key — check your connection");
      setValidating(false);
      return;
    }
    setValidating(false);
    setSaving(true);
    await api.setAgentConfig(selected.key, selected.api_key_env, keyValue.trim());
    await api.configureProvider(selected.key);
    setKeyValue("");
    setKeyError(null);
    await reload();
    setSaving(false);
  };

  const clearKey = async () => {
    if (!selected || !selectedEntry) return;
    await api.deleteAgentConfig(selected.key, selectedEntry.id);
    await reload();
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 py-12">
      <div className="w-full max-w-lg mx-auto px-6">
        <div className="text-center mb-10">
          <h1 className="text-3xl font-bold tracking-tight mb-2">llm flows</h1>
          <p className="text-gray-500 text-sm">Set up your environment to get started.</p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-3 mb-8">
          {[1, 2].map((s) => {
            const done = s === 1 && hasAnyKey;
            const disabled = s === 2 && !hasAnyKey;
            return (
              <button
                key={s}
                onClick={() => { if (!disabled) setStep(s); }}
                disabled={disabled}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  step === s
                    ? "bg-gray-800 text-white border border-gray-700"
                    : done
                      ? "text-green-400 hover:bg-gray-900"
                      : disabled
                        ? "text-gray-600 cursor-not-allowed"
                        : "text-gray-500 hover:bg-gray-900"
                }`}
              >
                {done ? (
                  <CheckCircle2 size={14} className="text-green-400" />
                ) : (
                  <span className={`w-5 h-5 rounded-full border text-xs flex items-center justify-center ${
                    step === s ? "border-blue-500 text-blue-400" : "border-gray-600 text-gray-500"
                  }`}>{s}</span>
                )}
                {s === 1 ? "Agents" : "Tools"}
              </button>
            );
          })}
        </div>

        {/* Step 1: Agents */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="mb-6">
              <div className="flex items-center gap-2.5 mb-2">
                <Bot size={18} className="text-blue-400" />
                <h2 className="text-lg font-semibold">Configure an API key</h2>
              </div>
              <p className="text-sm text-gray-500">
                Add an API key for at least one LLM provider to power your flows.
              </p>
            </div>

            {loading && <div className="text-gray-500 text-sm">Loading...</div>}

            {!loading && (
              <div className="space-y-4">
                {/* Provider dropdown */}
                <div className="relative">
                  <label className="text-xs font-medium text-gray-400 mb-1.5 block">Provider</label>
                  <button
                    onClick={() => setDropdownOpen((o) => !o)}
                    className="w-full flex items-center justify-between bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-sm text-left hover:border-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
                  >
                    {selected ? (
                      <span className="flex items-center gap-2.5">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${selectedConfigured ? "bg-green-400" : "bg-gray-600"}`} />
                        <span className="text-white font-medium">{selected.label}</span>
                        {selectedConfigured && (
                          <span className="text-[10px] text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded">configured</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-gray-500">Select a provider...</span>
                    )}
                    <ChevronDown size={14} className={`text-gray-500 transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
                  </button>

                  {dropdownOpen && (
                    <ul className="absolute z-50 mt-1 w-full bg-gray-900 border border-gray-700 rounded-xl shadow-lg overflow-hidden">
                      {providerList.map((prov) => (
                        <li key={prov.key}>
                          <button
                            onClick={() => { setSelectedProvider(prov.key); setDropdownOpen(false); setKeyValue(""); setKeyError(null); }}
                            className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-left transition-colors ${
                              prov.key === selectedProvider
                                ? "bg-gray-800 text-white"
                                : "text-gray-300 hover:bg-gray-800"
                            }`}
                          >
                            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${prov.configured ? "bg-green-400" : "bg-gray-600"}`} />
                            <span className="font-medium">{prov.label}</span>
                            {prov.configured && (
                              <span className="text-[10px] text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded ml-auto">configured</span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* API key input — shown after selecting a provider */}
                {selected && (
                  <div>
                    <label className="text-xs font-medium text-gray-400 mb-1.5 block">API Key</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="password"
                        value={selectedEntry ? "••••••••" : keyValue}
                        onChange={(e) => { if (!selectedEntry) { setKeyValue(e.target.value); setKeyError(null); } }}
                        readOnly={!!selectedEntry}
                        placeholder={selected.api_key_env}
                        className={`flex-1 bg-gray-900 border rounded-xl px-4 py-2.5 text-sm font-mono focus:outline-none ${
                          selectedEntry
                            ? "border-gray-700 text-gray-500 cursor-default"
                            : keyError
                              ? "border-red-500/60 focus:border-red-500"
                              : "border-gray-700 focus:border-blue-500"
                        }`}
                        onKeyDown={(e) => e.key === "Enter" && saveKey()}
                      />
                      {selectedEntry ? (
                        <button
                          onClick={clearKey}
                          className="text-xs text-gray-500 hover:text-red-400 transition-colors px-2"
                        >
                          clear
                        </button>
                      ) : keyValue.trim() ? (
                        <button
                          onClick={saveKey}
                          disabled={saving || validating}
                          className="text-sm px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white transition-colors whitespace-nowrap"
                        >
                          {validating ? "Validating..." : saving ? "Saving..." : "Save"}
                        </button>
                      ) : null}
                    </div>
                    {keyError && (
                      <p className="text-xs text-red-400 mt-1.5">{keyError}</p>
                    )}
                  </div>
                )}

                {/* Configured summary */}
                {hasAnyKey && (
                  <div className="flex items-center gap-2 pt-2 text-sm text-green-400">
                    <CheckCircle2 size={14} />
                    <span>
                      {configuredProviders.map((p) => p.label).join(", ")} configured
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="flex justify-end pt-4">
              <button
                onClick={() => setStep(2)}
                disabled={!hasAnyKey}
                className="flex items-center gap-1.5 px-5 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                Next
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Tools */}
        {step === 2 && (
          <ToolsStep onComplete={onComplete} onBack={() => setStep(1)} />
        )}
      </div>
    </div>
  );
}

function WelcomeToolCard({ tool, onUpdate }: { tool: import("@/api/types").ToolConfig; onUpdate: (t: import("@/api/types").ToolConfig) => void }) {
  const [localConfig, setLocalConfig] = useState<Record<string, string>>(tool.config);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [togglingEnabled, setTogglingEnabled] = useState(false);

  useEffect(() => { setLocalConfig(tool.config); }, [tool]);

  const toggleEnabled = async () => {
    setTogglingEnabled(true);
    try {
      const updated = await api.updateToolConfig(tool.id, { enabled: !tool.enabled });
      onUpdate(updated);
    } catch (e) { console.error("Failed to toggle tool:", e); }
    setTogglingEnabled(false);
  };

  const setField = (key: string, value: string) => {
    setLocalConfig((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
    setShowErrors(false);
  };

  const hasInvalidRequiredFields = () => {
    for (const field of tool.config_fields) {
      if (!field.show_when) continue;
      const visible = Object.entries(field.show_when).every(
        ([k, v]) => localConfig[k] === v,
      );
      if (visible && (field.type === "secret" || field.type === "text") && !localConfig[field.key]?.trim()) {
        return true;
      }
    }
    return false;
  };

  const saveConfig = async () => {
    if (hasInvalidRequiredFields()) {
      setShowErrors(true);
      return;
    }
    setShowErrors(false);
    setSaving(true);
    try {
      const updated = await api.updateToolConfig(tool.id, { config: localConfig });
      onUpdate(updated);
      setDirty(false);
    } catch (e) { console.error("Failed to save tool config:", e); }
    setSaving(false);
  };

  const inlineFields = (selectKey: string, optionValue: string) =>
    tool.config_fields.filter((f) => f.show_when && f.show_when[selectKey] === optionValue);

  const isTopLevel = (field: import("@/api/types").ToolConfigField) => !field.show_when;

  return (
    <div className={`rounded-xl border overflow-hidden transition-colors ${
      tool.enabled ? "border-blue-500/30 bg-blue-500/5" : "border-gray-800 bg-gray-900/50"
    }`}>
      <div className="flex items-center justify-between p-3">
        <div className="min-w-0">
          <span className="font-medium text-sm text-white">{tool.name}</span>
          <p className="text-xs text-gray-500 mt-0.5">{tool.description}</p>
        </div>
        <button
          onClick={toggleEnabled}
          disabled={togglingEnabled}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0 ml-4 ${
            tool.enabled ? "bg-blue-500" : "bg-gray-700"
          }`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            tool.enabled ? "translate-x-6" : "translate-x-1"
          }`} />
        </button>
      </div>

      {tool.enabled && tool.config_fields.length > 0 && (
        <div className="border-t border-gray-800/60 p-3 space-y-3">
          {tool.config_fields.filter(isTopLevel).map((field) => (
            <div key={field.key}>
              <label className="text-xs font-medium text-gray-400 mb-1.5 block">{field.label}</label>
              {field.type === "select" ? (
                <div className="space-y-1.5">
                  {field.options?.map((opt) => {
                    const isActive = localConfig[field.key] === opt.value;
                    const nested = inlineFields(field.key, opt.value);
                    return (
                      <div
                        key={opt.value}
                        className={`flex items-center gap-2.5 rounded-lg border p-2.5 transition-colors ${
                          isActive
                            ? "border-blue-500/50 bg-blue-500/5"
                            : "border-gray-800 bg-gray-900 hover:border-gray-700 cursor-pointer"
                        }`}
                        onClick={() => !isActive && setField(field.key, opt.value)}
                      >
                        <div className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                          isActive ? "border-blue-500" : "border-gray-600"
                        }`}>
                          {isActive && <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />}
                        </div>
                        <span className="font-medium text-sm text-white whitespace-nowrap">{opt.label}</span>
                        {opt.hint && !isActive && (
                          <span className="text-[10px] text-gray-500">{opt.hint}</span>
                        )}
                        {isActive && nested.length > 0 && nested.map((nf) => {
                          const missing = showErrors && !localConfig[nf.key]?.trim();
                          return (
                            <div key={nf.key} className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                              <input
                                type={nf.type === "secret" ? "password" : "text"}
                                value={localConfig[nf.key] ?? ""}
                                onChange={(e) => setField(nf.key, e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && saveConfig()}
                                placeholder={nf.label}
                                className={`bg-gray-800 border rounded px-2 py-1 text-xs w-48 font-mono focus:outline-none ${
                                  missing ? "border-amber-500/60" : "border-gray-700 focus:border-gray-500"
                                }`}
                              />
                              {missing && (
                                <span className="text-[11px] text-amber-400 whitespace-nowrap">Required</span>
                              )}
                            </div>
                          );
                        })}
                        {isActive && nested.length === 0 && opt.hint && (
                          <span className="text-[10px] text-gray-500">{opt.hint}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <input
                  type={field.type === "secret" ? "password" : "text"}
                  value={localConfig[field.key] ?? ""}
                  onChange={(e) => setField(field.key, e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && saveConfig()}
                  placeholder={field.placeholder}
                  className="bg-gray-800 border border-gray-700 rounded px-2.5 py-1.5 text-sm w-72 font-mono focus:outline-none focus:border-gray-500"
                />
              )}
            </div>
          ))}

          {dirty && (
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={saveConfig}
                disabled={saving}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 transition-colors"
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolsStep({ onComplete, onBack }: { onComplete: () => void; onBack: () => void }) {
  const [tools, setTools] = useState<import("@/api/types").ToolConfig[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const loaded = await api.getToolsConfig();
        const disabled = await Promise.all(
          loaded.map(async (t) => {
            if (t.enabled) {
              try { return await api.updateToolConfig(t.id, { enabled: false }); } catch { /* ignore */ }
            }
            return t;
          })
        );
        setTools(disabled);
      } catch (e) {
        console.error("Failed to load tools:", e);
      }
      setLoading(false);
    })();
  }, []);

  const handleUpdate = (updated: import("@/api/types").ToolConfig) => {
    setTools((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
  };

  return (
    <div className="space-y-4">
      <div className="mb-6">
        <div className="flex items-center gap-2.5 mb-2">
          <Wrench size={18} className="text-blue-400" />
          <h2 className="text-lg font-semibold">Agent tools</h2>
        </div>
        <p className="text-sm text-gray-500">
          Tools extend agent capabilities. Toggle the ones you want available during runs.
        </p>
      </div>

      {loading && <div className="text-gray-500 text-sm">Loading...</div>}

      {!loading && (
        <div className="space-y-3">
          {tools.map((tool) => (
            <WelcomeToolCard key={tool.id} tool={tool} onUpdate={handleUpdate} />
          ))}
        </div>
      )}

      <p className="text-xs text-gray-600 pt-2">
        You can reconfigure tools anytime on the Tools page.
      </p>

      <div className="flex justify-between pt-4">
        <button
          onClick={onBack}
          className="px-4 py-2 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
        >
          Back
        </button>
        <button
          onClick={onComplete}
          className="px-5 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          Get started
        </button>
      </div>
    </div>
  );
}
