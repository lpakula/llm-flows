import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type { AuditResult } from "@/api/types";
import { X, RefreshCw, ShieldAlert, ShieldOff, ShieldCheck, ExternalLink, Loader2 } from "lucide-react";

export interface AuditResource {
  name: string;
  key: string;
  link?: string;
  audit: AuditResult | null;
}

function statusOrder(status: AuditResult["status"] | null | undefined): number {
  if (status === "unsafe") return 0;
  if (!status) return 1;
  if (status === "error") return 2;
  if (status === "pending") return 3;
  return 4;
}

function StatusIcon({ status, auditing }: { status: AuditResult["status"] | null | undefined; auditing?: boolean }) {
  if (auditing) {
    return (
      <span className="text-amber-400 shrink-0 animate-spin">
        <Loader2 size={14} />
      </span>
    );
  }
  if (status === "unsafe") {
    return (
      <span title="Unsafe" className="text-red-400 shrink-0">
        <ShieldAlert size={14} />
      </span>
    );
  }
  if (status === "safe") {
    return (
      <span title="Safe" className="text-emerald-400 shrink-0">
        <ShieldCheck size={14} />
      </span>
    );
  }
  return (
    <span title="Unaudited" className="text-amber-400 shrink-0">
      <ShieldOff size={14} />
    </span>
  );
}

function ResourceItem({ resource, onNavigate, auditing }: { resource: AuditResource; onNavigate?: (path: string) => void; auditing?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const hasFindings = resource.audit?.status === "unsafe" && resource.audit.findings?.length > 0;

  return (
    <div className="border-b border-gray-800 last:border-b-0">
      <div
        className={`flex items-center gap-3 px-5 py-2.5 ${hasFindings ? "cursor-pointer hover:bg-gray-800/50" : ""}`}
        onClick={() => hasFindings && setExpanded(!expanded)}
      >
        <span className="text-sm text-gray-300 flex-1 min-w-0 truncate">{resource.name}</span>
        {resource.link && onNavigate && (
          <button
            onClick={(e) => { e.stopPropagation(); onNavigate(resource.link!); }}
            className="text-gray-500 hover:text-gray-300 shrink-0 transition"
            title="Go to page"
          >
            <ExternalLink size={12} />
          </button>
        )}
        <StatusIcon status={resource.audit?.status} auditing={auditing} />
      </div>
      {expanded && resource.audit && (
        <div className="px-5 pb-3 space-y-1">
          {resource.audit.summary && (
            <p className="text-xs text-red-300/80">{resource.audit.summary}</p>
          )}
          {resource.audit.findings?.map((f, i) => (
            <p key={i} className="text-[11px] text-red-300/60">
              <span className="text-red-400 font-mono mr-1">•</span>{f}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function Section({ title, resources, onNavigate, auditingKeys }: { title: string; resources: AuditResource[]; onNavigate: (path: string) => void; auditingKeys: Set<string> }) {
  const issues = resources
    .filter((r) => r.audit?.status !== "safe" || auditingKeys.has(r.key))
    .sort((a, b) => statusOrder(a.audit?.status) - statusOrder(b.audit?.status));

  return (
    <div>
      <div className="px-5 py-2 bg-gray-800/40">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium">{title}</span>
      </div>
      {issues.length === 0 ? (
        <div className="flex items-center gap-3 px-5 py-2.5">
          <span className="text-sm text-gray-300 flex-1">No issues</span>
          <span className="text-emerald-400 shrink-0" title="Safe">
            <ShieldCheck size={14} />
          </span>
        </div>
      ) : (
        issues.map((r) => (
          <ResourceItem key={r.key} resource={r} onNavigate={onNavigate} auditing={auditingKeys.has(r.key)} />
        ))
      )}
    </div>
  );
}

export function SecurityAuditModal({
  open,
  onClose,
  flows,
  skills,
  onAuditFlow,
  onAuditSkill,
  onComplete,
}: {
  open: boolean;
  onClose: () => void;
  flows: AuditResource[];
  skills: AuditResource[];
  onAuditFlow: (key: string) => Promise<AuditResult>;
  onAuditSkill: (key: string) => Promise<AuditResult>;
  onComplete: () => void;
}) {
  const navigate = useNavigate();
  const [auditing, setAuditing] = useState(false);
  const [auditingKeys, setAuditingKeys] = useState<Set<string>>(new Set());
  const [overrides, setOverrides] = useState<Map<string, AuditResult>>(new Map());

  const applyOverrides = useCallback((resources: AuditResource[]): AuditResource[] =>
    resources.map((r) => overrides.has(r.key) ? { ...r, audit: overrides.get(r.key)! } : r),
  [overrides]);

  if (!open) return null;

  const resolvedFlows = applyOverrides(flows);
  const resolvedSkills = applyOverrides(skills);
  const allResources = [...resolvedFlows, ...resolvedSkills];
  const unsafeCount = allResources.filter((r) => r.audit?.status === "unsafe").length;
  const unauditedCount = allResources.filter((r) => !r.audit?.status).length;
  const totalIssues = unsafeCount + unauditedCount;

  const handleRunAll = async () => {
    setAuditing(true);
    const newOverrides = new Map(overrides);
    const needsAudit = (r: AuditResource) => r.audit?.status !== "safe";
    const flowsToAudit = resolvedFlows.filter(needsAudit);
    const skillsToAudit = resolvedSkills.filter(needsAudit);
    const keys = new Set([...flowsToAudit.map((f) => f.key), ...skillsToAudit.map((s) => s.key)]);
    setAuditingKeys(keys);

    for (const f of flowsToAudit) {
      try {
        const result = await onAuditFlow(f.key);
        newOverrides.set(f.key, result);
        setOverrides(new Map(newOverrides));
      } catch { /* ignore */ }
      setAuditingKeys((prev) => { const next = new Set(prev); next.delete(f.key); return next; });
    }

    for (const s of skillsToAudit) {
      try {
        const result = await onAuditSkill(s.key);
        newOverrides.set(s.key, result);
        setOverrides(new Map(newOverrides));
      } catch { /* ignore */ }
      setAuditingKeys((prev) => { const next = new Set(prev); next.delete(s.key); return next; });
    }

    setAuditing(false);
    onComplete();
  };

  const handleNavigate = (path: string) => { onClose(); navigate(path); };

  const toAuditCount = [...resolvedFlows, ...resolvedSkills].filter((r) => r.audit?.status !== "safe").length;
  const done = auditing ? toAuditCount - auditingKeys.size : 0;
  const total = toAuditCount;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 className="text-base font-semibold text-white">Security Audit</h3>
          <div className="flex items-center gap-3">
            {(toAuditCount > 0 || auditing) && (
              <button
                onClick={handleRunAll}
                disabled={auditing}
                className="flex items-center gap-1.5 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-50 transition font-medium"
              >
                <RefreshCw size={12} className={auditing ? "animate-spin" : ""} />
                {auditing ? `Auditing ${done}/${total}...` : "Run all"}
              </button>
            )}
            <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 px-5 py-3 border-b border-gray-800 bg-gray-900/50">
          {unsafeCount > 0 && (
            <span className="text-xs text-red-400 font-medium">{unsafeCount} unsafe</span>
          )}
          {unauditedCount > 0 && (
            <span className="text-xs text-amber-400 font-medium">{unauditedCount} unaudited</span>
          )}
          {totalIssues === 0 && !auditing && (
            <span className="text-xs text-emerald-400 font-medium">All resources passed security audit</span>
          )}
          {auditing && totalIssues === 0 && (
            <span className="text-xs text-amber-400 font-medium">Auditing...</span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto">
          <Section title="Flows" resources={resolvedFlows} onNavigate={handleNavigate} auditingKeys={auditingKeys} />
          <Section title="Skills" resources={resolvedSkills} onNavigate={handleNavigate} auditingKeys={auditingKeys} />
        </div>
      </div>
    </div>
  );
}
