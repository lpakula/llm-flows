import { useState, useEffect, useRef } from "react";
import { api } from "@/api/client";
import type { DaemonConfig } from "@/api/types";

type RowType = "number" | "bool" | "string" | "select";

interface SelectOption {
  value: string;
  label: string;
}

interface SettingRow {
  key: keyof DaemonConfig;
  label: string;
  description: string;
  unit?: string;
  type: RowType;
  min?: number;
  options?: SelectOption[];
}

const ROWS: SettingRow[] = [
  {
    key: "poll_interval_seconds",
    label: "Poll interval",
    description: "How often the daemon checks for pending task runs",
    unit: "seconds",
    type: "number",
    min: 1,
  },
  {
    key: "run_timeout_minutes",
    label: "Run timeout",
    description: "Maximum time a single task run is allowed to take",
    unit: "minutes",
    type: "number",
    min: 1,
  },
  {
    key: "gate_timeout_seconds",
    label: "Gate timeout",
    description: "Maximum time to wait for a gate condition to pass",
    unit: "seconds",
    type: "number",
    min: 1,
  },
  {
    key: "summarizer_language",
    label: "Summarizer language",
    description: "Language for auto-generated run summaries",
    type: "select",
    options: [
      { value: "English", label: "English" },
      { value: "Arabic", label: "Arabic" },
      { value: "Chinese", label: "Chinese" },
      { value: "Dutch", label: "Dutch" },
      { value: "French", label: "French" },
      { value: "German", label: "German" },
      { value: "Hindi", label: "Hindi" },
      { value: "Italian", label: "Italian" },
      { value: "Japanese", label: "Japanese" },
      { value: "Korean", label: "Korean" },
      { value: "Polish", label: "Polish" },
      { value: "Portuguese", label: "Portuguese" },
      { value: "Russian", label: "Russian" },
      { value: "Spanish", label: "Spanish" },
      { value: "Turkish", label: "Turkish" },
      { value: "Ukrainian", label: "Ukrainian" },
    ],
  },
];

function SelectDropdown({ value, options, onSelect }: {
  value: string;
  options: SelectOption[];
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const selected = options.find((o) => o.value === value);

  return (
    <div ref={ref} className="relative inline-block" {...(open ? { "data-dropdown-open": "" } : {})}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm font-mono focus:outline-none focus:border-gray-500 cursor-pointer flex items-center gap-1.5"
      >
        {selected?.label || value}
        <span className="text-[9px] text-gray-500">▼</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 min-w-[140px] max-h-64 overflow-y-auto">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => { onSelect(opt.value); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-700 transition-colors ${opt.value === value ? "text-blue-400" : "text-gray-300"}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function SettingsView() {
  const [config, setConfig] = useState<DaemonConfig | null>(null);
  const [editing, setEditing] = useState<Partial<DaemonConfig>>({});
  const [savingKey, setSavingKey] = useState<keyof DaemonConfig | null>(null);
  const [savedKey, setSavedKey] = useState<keyof DaemonConfig | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const c = await api.getDaemonConfig();
        setConfig(c);
      } catch (e) {
        console.error("Failed to load settings:", e);
      }
      setLoading(false);
    })();
  }, []);

  const saveRow = async (key: keyof DaemonConfig) => {
    if (!config) return;
    const raw = editing[key];
    if (raw === undefined) return;
    setSavingKey(key);
    try {
      const updated = await api.updateDaemonConfig({ [key]: raw } as Partial<DaemonConfig>);
      setConfig(updated);
      setEditing((prev) => { const next = { ...prev }; delete next[key]; return next; });
      setSavedKey(key);
      setTimeout(() => setSavedKey((k) => (k === key ? null : k)), 2000);
    } catch (e) {
      console.error("Failed to save setting:", e);
    }
    setSavingKey(null);
  };

  const getValue = (row: SettingRow): string | number | boolean => {
    if (editing[row.key] !== undefined) return editing[row.key] as string | number | boolean;
    if (config) return config[row.key] as string | number | boolean;
    return row.type === "bool" ? false : row.type === "number" ? 0 : "";
  };

  const isDirty = (key: keyof DaemonConfig) => editing[key] !== undefined;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-2">Settings</h2>
      <p className="text-xs text-gray-500 mb-6">
        Stored in <span className="font-mono">~/.llmflows/config.toml</span>. Daemon/UI settings take effect after a restart.
      </p>

      {loading && <div className="text-gray-500">Loading...</div>}

      {!loading && config && (
        <div className="border border-gray-800 rounded-xl overflow-clip [&:has([data-dropdown-open])]:overflow-visible">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900/60">
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Setting</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden md:table-cell">Description</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Value</th>
                <th className="px-4 py-3 w-20"></th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row, i) => {
                const val = getValue(row);
                const dirty = isDirty(row.key);
                const saving = savingKey === row.key;
                const saved = savedKey === row.key;
                return (
                  <tr
                    key={row.key}
                    className={`bg-gray-900 ${i < ROWS.length - 1 ? "border-b border-gray-800" : ""}`}
                  >
                    <td className="px-4 py-3 font-medium text-white whitespace-nowrap">{row.label}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">{row.description}</td>
                    <td className="px-4 py-3">
                      {row.type === "select" ? (
                        <SelectDropdown
                          value={val as string}
                          options={row.options!}
                          onSelect={async (next) => {
                            setEditing((prev) => ({ ...prev, [row.key]: next }));
                            setSavingKey(row.key);
                            try {
                              const updated = await api.updateDaemonConfig({ [row.key]: next } as Partial<DaemonConfig>);
                              setConfig(updated);
                              setEditing((prev) => { const n = { ...prev }; delete n[row.key]; return n; });
                              setSavedKey(row.key);
                              setTimeout(() => setSavedKey((k) => (k === row.key ? null : k)), 2000);
                            } catch (e2) {
                              console.error(e2);
                            }
                            setSavingKey(null);
                          }}
                        />
                      ) : row.type === "bool" ? (
                        <button
                          onClick={async () => {
                            const next = !val;
                            setEditing((prev) => ({ ...prev, [row.key]: next }));
                            setSavingKey(row.key);
                            try {
                              const updated = await api.updateDaemonConfig({ [row.key]: next } as Partial<DaemonConfig>);
                              setConfig(updated);
                              setEditing((prev) => { const n = { ...prev }; delete n[row.key]; return n; });
                              setSavedKey(row.key);
                              setTimeout(() => setSavedKey((k) => (k === row.key ? null : k)), 2000);
                            } catch (e) {
                              console.error(e);
                            }
                            setSavingKey(null);
                          }}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${val ? "bg-blue-600" : "bg-gray-700"}`}
                        >
                          <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${val ? "translate-x-4" : "translate-x-1"}`} />
                        </button>
                      ) : (
                        <div className="flex items-center gap-2">
                          <input
                            type={row.type === "number" ? "number" : "text"}
                            min={row.min}
                            value={val as string | number}
                            onChange={(e) => {
                              const v = row.type === "number" ? (parseInt(e.target.value) || 0) : e.target.value;
                              setEditing((prev) => ({ ...prev, [row.key]: v }));
                            }}
                            onKeyDown={(e) => e.key === "Enter" && saveRow(row.key)}
                            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-28 font-mono focus:outline-none focus:border-gray-500"
                          />
                          {row.unit && <span className="text-xs text-gray-600">{row.unit}</span>}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {row.type !== "bool" && row.type !== "select" && (
                        saved ? (
                          <span className="text-xs text-green-400">Saved</span>
                        ) : (
                          <button
                            onClick={() => saveRow(row.key)}
                            disabled={!dirty || saving}
                            className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                          >
                            {saving ? "Saving…" : "Save"}
                          </button>
                        )
                      )}
                      {(row.type === "bool" || row.type === "select") && saved && (
                        <span className="text-xs text-green-400">Saved</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
