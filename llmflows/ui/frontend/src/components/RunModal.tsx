import { useState, useRef, useEffect } from "react";
import { api } from "@/api/client";
import type { Flow, FlowWarning } from "@/api/types";

function FlowDropdown({
  flows,
  selectedId,
  onChange,
}: {
  flows: Flow[];
  selectedId: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = flows.find((f) => f.id === selectedId);
  const filtered = flows.filter((f) =>
    f.name.toLowerCase().includes(search.toLowerCase()) ||
    (f.description || "").toLowerCase().includes(search.toLowerCase()),
  );

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    if (open) {
      setSearch("");
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-left flex items-center justify-between gap-2 hover:border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
      >
        <span className={selected ? "text-gray-200 font-mono" : "text-gray-500"}>
          {selected ? selected.name : "Select flow..."}
        </span>
        <span className="text-gray-500 text-[10px] shrink-0">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="absolute z-10 mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
          <div className="p-2 border-b border-gray-700">
            <input
              ref={inputRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search flows..."
              className="w-full bg-gray-900 border border-gray-700 rounded px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <ul className="max-h-56 overflow-y-auto">
            {filtered.length === 0 ? (
              <li className="px-3 py-3 text-xs text-gray-600 text-center">No flows found</li>
            ) : (
              filtered.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    onClick={() => { onChange(f.id); setOpen(false); }}
                    className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                      f.id === selectedId
                        ? "bg-blue-600/20 text-blue-300"
                        : "text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    <span className="font-mono">{f.name}</span>
                    {f.description && (
                      <span className="text-xs text-gray-500 ml-2">{f.description}</span>
                    )}
                    <span className="text-[10px] text-gray-600 ml-2">{f.step_count} steps</span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ScheduleModal({
  flows,
  onClose,
  onSubmit,
}: {
  flows: Flow[];
  onClose: () => void;
  onSubmit: (flowId: string) => Promise<void>;
}) {
  const [selectedFlowId, setSelectedFlowId] = useState(flows[0]?.id ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [warnings, setWarnings] = useState<FlowWarning[]>([]);
  const [loadingWarnings, setLoadingWarnings] = useState(false);

  const hasBlockingWarnings = warnings.some(
    (w) => w.warning_type === "missing_variable" || w.warning_type === "missing_tool",
  );

  useEffect(() => {
    if (!selectedFlowId) { setWarnings([]); return; }
    let cancelled = false;
    setLoadingWarnings(true);
    api.validateFlow(selectedFlowId).then((res) => {
      if (!cancelled) setWarnings(res.warnings);
    }).catch(() => {
      if (!cancelled) setWarnings([]);
    }).finally(() => {
      if (!cancelled) setLoadingWarnings(false);
    });
    return () => { cancelled = true; };
  }, [selectedFlowId]);

  const submit = async () => {
    if (!selectedFlowId) return;
    setSubmitting(true);
    try {
      await onSubmit(selectedFlowId);
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-base font-semibold mb-1">New Run</h2>
        <p className="text-xs text-gray-500 mb-5">Select a flow to execute</p>

        <div className="space-y-5">
          <div>
            <label className="text-sm text-gray-400 block mb-2">Flow</label>
            <FlowDropdown
              flows={flows}
              selectedId={selectedFlowId}
              onChange={setSelectedFlowId}
            />
          </div>

          {flows.length === 0 && (
            <p className="text-xs text-gray-600 italic">No flows defined for this space.</p>
          )}
        </div>

        {!loadingWarnings && warnings.length > 0 && (
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg px-4 py-2 mt-4">
            <p className="text-xs text-amber-400 font-medium mb-1">
              {hasBlockingWarnings ? "Cannot run — missing requirements:" : "Configuration warnings:"}
            </p>
            <ul className="space-y-0.5">
              {warnings.map((w, i) => (
                <li key={i} className="text-xs text-amber-300/80">
                  {w.step_name && <span className="font-mono mr-1">{w.step_name}:</span>}
                  {w.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || !selectedFlowId || hasBlockingWarnings || loadingWarnings}
            className="px-5 py-2 text-sm bg-blue-600 text-white rounded-xl hover:bg-blue-500 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitting ? "Scheduling…" : "Run"}
          </button>
        </div>
      </div>
    </div>
  );
}
