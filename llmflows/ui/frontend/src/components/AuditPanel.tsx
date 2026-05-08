import { useState } from "react";
import { RefreshCw, MessageSquareText } from "lucide-react";
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

  const busy = running || exempting;

  if (audit?.status === "safe") return null;

  if (!audit?.status) {
    return (
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-5 py-3 mb-4">
        <div className="flex items-center justify-between">
          <span className="text-xs text-amber-300/80">
            No security audit yet.
          </span>
          <button
            onClick={handleRunAudit}
            disabled={running}
            className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-50 transition font-medium"
          >
            <RefreshCw size={11} className={running ? "animate-spin" : ""} />
            {running ? "Auditing..." : "Run audit"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-5 py-3 mb-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-red-400">Security Audit</h4>
        <button
          onClick={handleRunAudit}
          disabled={busy}
          className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50 transition font-medium"
        >
          <RefreshCw size={11} className={running ? "animate-spin" : ""} />
          {running ? "Auditing..." : "Re-audit"}
        </button>
      </div>

      {audit.summary && (
        <p className="text-xs text-red-300/80 mt-2">{audit.summary}</p>
      )}

      {audit.findings && audit.findings.length > 0 && (
        <ul className="mt-2 space-y-1">
          {audit.findings.map((f, i) => (
            <li key={i} className="text-xs text-red-300/80">
              {audit.findings!.length > 1 && <span className="text-red-400 font-mono mr-1">•</span>}
              {f}
            </li>
          ))}
        </ul>
      )}

      {onExempt && (
        <div className="mt-3 pt-3 border-t border-red-500/20">
          {!showExempt ? (
            <button
              onClick={() => setShowExempt(true)}
              className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 font-medium transition"
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
                className="w-full bg-gray-800/50 border border-red-500/20 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none focus:border-red-500/40 resize-y"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={handleExempt}
                  disabled={busy || !explanation.trim()}
                  className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50 transition font-medium"
                >
                  <RefreshCw size={10} className={exempting ? "animate-spin" : ""} />
                  {exempting ? "Analyzing..." : "Submit and re-audit"}
                </button>
                <button
                  onClick={() => { setShowExempt(false); setExplanation(""); }}
                  disabled={busy}
                  className="text-xs text-red-300/50 hover:text-red-300 disabled:opacity-50 transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
