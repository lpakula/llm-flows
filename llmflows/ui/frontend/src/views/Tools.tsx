import { useState, useEffect } from "react";
import { api } from "@/api/client";
import type { ToolConfig, ToolConfigField } from "@/api/types";

function ToolCard({ tool, onUpdate }: { tool: ToolConfig; onUpdate: (t: ToolConfig) => void }) {
  const [localConfig, setLocalConfig] = useState<Record<string, string>>(tool.config);
  const [savingField, setSavingField] = useState<string | null>(null);
  const [savedField, setSavedField] = useState<string | null>(null);
  const [togglingEnabled, setTogglingEnabled] = useState(false);

  useEffect(() => {
    setLocalConfig(tool.config);
  }, [tool]);

  const toggleEnabled = async () => {
    setTogglingEnabled(true);
    try {
      const updated = await api.updateToolConfig(tool.id, { enabled: !tool.enabled });
      onUpdate(updated);
    } catch (e) {
      console.error("Failed to toggle tool:", e);
    }
    setTogglingEnabled(false);
  };

  const [dirty, setDirty] = useState(false);
  const [showErrors, setShowErrors] = useState(false);

  const saveConfig = async () => {
    if (hasInvalidRequiredFields()) {
      setShowErrors(true);
      return;
    }
    setShowErrors(false);
    setSavingField("__all__");
    try {
      const updated = await api.updateToolConfig(tool.id, { config: localConfig });
      onUpdate(updated);
      setDirty(false);
      setSavedField("__all__");
      setTimeout(() => setSavedField((k) => (k === "__all__" ? null : k)), 2000);
    } catch (e) {
      console.error("Failed to save tool config:", e);
    }
    setSavingField(null);
  };

  const setField = (key: string, value: string) => {
    setLocalConfig((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
    setShowErrors(false);
  };

  const inlineFields = (selectKey: string, optionValue: string) =>
    tool.config_fields.filter(
      (f) => f.show_when && f.show_when[selectKey] === optionValue,
    );

  const isTopLevel = (field: ToolConfigField) => !field.show_when;

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

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 overflow-hidden">
      <div className="flex items-center justify-between p-4">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-white">{tool.name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{tool.description}</p>
        </div>
        <button
          onClick={toggleEnabled}
          disabled={togglingEnabled}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0 ml-4 ${
            tool.enabled ? "bg-blue-500" : "bg-gray-700"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              tool.enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      {tool.enabled && tool.config_fields.length > 0 && (
        <div className="border-t border-gray-800 p-4 space-y-4">
          {tool.config_fields.filter(isTopLevel).map((field) => (
            <div key={field.key}>
              <label className="text-xs font-medium text-gray-400 mb-1.5 block">
                {field.label}
              </label>

              {field.type === "select" ? (
                <div className="space-y-1.5">
                  {field.options?.map((opt) => {
                    const isActive = localConfig[field.key] === opt.value;
                    const nested = inlineFields(field.key, opt.value);

                    return (
                      <div
                        key={opt.value}
                        className={`flex items-center gap-2.5 rounded-lg border p-3 transition-colors ${
                          isActive
                            ? "border-blue-500/50 bg-blue-500/5"
                            : "border-gray-800 bg-gray-900 hover:border-gray-700 cursor-pointer"
                        }`}
                        onClick={() => !isActive && setField(field.key, opt.value)}
                      >
                        <div
                          className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                            isActive ? "border-blue-500" : "border-gray-600"
                          }`}
                        >
                          {isActive && (
                            <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                          )}
                        </div>
                        <span className="font-medium text-sm text-white whitespace-nowrap">
                          {opt.label}
                        </span>
                        {opt.hint && !isActive && (
                          <span className="text-[10px] text-gray-500">
                            {opt.hint}
                          </span>
                        )}
                        {isActive && nested.length > 0 && nested.map((nf) => {
                          const missing = showErrors && !localConfig[nf.key]?.trim();
                          return (
                            <div key={nf.key} className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                              <input
                                type={nf.type === "secret" ? "password" : "text"}
                                value={localConfig[nf.key] ?? ""}
                                onChange={(e) => setField(nf.key, e.target.value)}
                                onKeyDown={(e) =>
                                  e.key === "Enter" && !hasInvalidRequiredFields() && saveConfig()
                                }
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
                          <span className="text-[10px] text-gray-500">
                            {opt.hint}
                          </span>
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
                  onKeyDown={(e) =>
                    e.key === "Enter" && !hasInvalidRequiredFields() && saveConfig()
                  }
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
                disabled={savingField === "__all__"}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {savingField === "__all__" ? "Saving..." : "Save"}
              </button>
              {savedField === "__all__" && (
                <span className="text-xs text-green-400">Saved</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolsView() {
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setTools(await api.getToolsConfig());
      } catch (e) {
        console.error("Failed to load tools config:", e);
      }
      setLoading(false);
    })();
  }, []);

  const handleUpdate = (updated: ToolConfig) => {
    setTools((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-2">Tools</h2>
      <p className="text-xs text-gray-500 mb-6">
        Enable tools to extend agent capabilities. Each tool adds new
        functionality to all runs.
      </p>

      {loading && <div className="text-gray-500">Loading...</div>}

      {!loading && (
        <div className="space-y-3">
          {tools.map((tool) => (
            <ToolCard key={tool.id} tool={tool} onUpdate={handleUpdate} />
          ))}
          {tools.length === 0 && (
            <p className="text-sm text-gray-500">No tools available.</p>
          )}
        </div>
      )}
    </div>
  );
}
