import { useState } from "react";
import { RefreshCw, MessageSquareText } from "lucide-react";
import { AuditBadge } from "./AuditBadge";
import type { AuditResult } from "@/api/types";

export function AuditPanel({
  audit,
  onRunAudit,
  onExempt,
  onAuditComplete,
}: {
  audit?: AuditResult | null;
  onRunAudit: () => Promise<AuditResult>;
  onExempt?: (explanation: string) => Promise<AuditResult>;
  onAuditComplete: (result: AuditResult) => void;
}) {
  const [running, setRunning] = useState(false);
  const [exempting, setExempting] = useState(false);
  const [showExempt, setShowExempt] = useState(false);
  const [explanation, setExplanation] = useState("");

  const handleRunAudit = async () => {
    setRunning(true);
    try {
      const result = await onRunAudit();
      onAuditComplete(result);
    } catch {
      // ignore
    } finally {
      setRunning(false);
    }
  };

  const handleExempt = async () => {
    if (!onExempt || !explanation.trim()) return;
    setExempting(true);
    try {
      const result = await onExempt(explanation.trim());
      onAuditComplete(result);
      setShowExempt(false);
    } catch {
      // ignore
    } finally {
      setExempting(false);
    }
  };

  const borderColor = audit?.status === "safe"
    ? "border-emerald-500/30"
    : audit?.status === "unsafe"
    ? "border-red-500/30"
    : !audit?.status
    ? "border-amber-500/40"
    : "border-gray-700";

  const busy = running || exempting;

  if (audit?.status === "safe") return null;

  return (
    <div className={`border ${borderColor} rounded-lg p-3 mb-4 ${!audit?.status ? "bg-amber-500/5" : audit?.status === "unsafe" ? "bg-red-500/5" : ""}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-300">Security Audit</span>
          <AuditBadge audit={audit} size="md" />
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRunAudit}
            disabled={busy}
            className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200 disabled:opacity-50 transition"
            title="Run security audit"
          >
            <RefreshCw size={11} className={running ? "animate-spin" : ""} />
            {running ? "Auditing..." : audit?.status ? "Re-audit" : "Run audit"}
          </button>
        </div>
      </div>

      {audit?.summary && (
        <p className="text-xs text-gray-400 mb-1">{audit.summary}</p>
      )}

      {audit?.findings && audit.findings.length > 0 && (
        <ul className="mt-2 space-y-0.5 list-disc list-inside marker:text-red-400">
          {audit.findings.map((f, i) => (
            <li key={i} className="text-[11px] text-red-300/80">{f}</li>
          ))}
        </ul>
      )}

      {onExempt && audit?.status && audit.status !== "safe" && (
        <div className="mt-3">
          {!showExempt ? (
            <button
              onClick={() => setShowExempt(true)}
              className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 transition"
            >
              <MessageSquareText size={11} />
              Exempt — explain why these are safe
            </button>
          ) : (
            <div className="space-y-2">
              <textarea
                value={explanation}
                onChange={(e) => setExplanation(e.target.value)}
                placeholder="Explain why the flagged patterns are expected behavior (e.g. 'rm -rf in step 2 cleans the build directory before rebuilding')..."
                rows={3}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:border-blue-500 resize-y"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={handleExempt}
                  disabled={busy || !explanation.trim()}
                  className="flex items-center gap-1 text-[11px] px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded-md disabled:opacity-40 transition"
                >
                  <RefreshCw size={10} className={exempting ? "animate-spin" : ""} />
                  {exempting ? "Analyzing..." : "Submit and re-audit"}
                </button>
                <button
                  onClick={() => { setShowExempt(false); setExplanation(""); }}
                  disabled={busy}
                  className="text-[11px] text-gray-500 hover:text-gray-300 disabled:opacity-50 transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {!audit?.status && (
        <div className="flex items-center gap-2">
          <p className="text-xs text-gray-500">No audit yet.</p>
          <button
            onClick={handleRunAudit}
            disabled={running}
            className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50"
          >
            Run audit
          </button>
        </div>
      )}
    </div>
  );
}
