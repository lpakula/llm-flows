import { ShieldCheck, ShieldAlert, ShieldQuestion, ShieldOff } from "lucide-react";
import type { AuditResult } from "@/api/types";

export function AuditBadge({ audit, size = "sm", hideIfSafe, hideIfUnsafe, showUnverified }: { audit?: AuditResult | null; size?: "sm" | "md"; hideIfSafe?: boolean; hideIfUnsafe?: boolean; showUnverified?: boolean }) {
  if (!audit || !audit.status) {
    if (showUnverified) {
      const textSize = size === "sm" ? "text-[9px]" : "text-[11px]";
      const iconSize = size === "sm" ? 9 : 12;
      return (
        <span title="Security Audit" className={`inline-flex items-center gap-0.5 text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded font-medium ${textSize}`}>
          <ShieldOff size={iconSize} />
          Unverified
        </span>
      );
    }
    return null;
  }
  if (hideIfSafe && audit.status === "safe") return null;
  if (hideIfUnsafe && audit.status !== "safe") return null;

  const config = {
    safe: { icon: ShieldCheck, label: "Safe", color: "text-emerald-400", bg: "bg-emerald-400/10" },
    unsafe: { icon: ShieldAlert, label: "Unsafe", color: "text-red-400", bg: "bg-red-400/10" },
    pending: { icon: ShieldQuestion, label: "Auditing...", color: "text-amber-400", bg: "bg-amber-400/10" },
    error: { icon: ShieldQuestion, label: "Audit error", color: "text-gray-400", bg: "bg-gray-400/10" },
  }[audit.status];

  if (!config) return null;
  const Icon = config.icon;
  const textSize = size === "sm" ? "text-[9px]" : "text-[11px]";
  const iconSize = size === "sm" ? 9 : 12;

  return (
    <span title="Security Audit" className={`inline-flex items-center gap-0.5 ${config.color} ${config.bg} px-1.5 py-0.5 rounded font-medium ${textSize}`}>
      <Icon size={iconSize} />
      {config.label}
    </span>
  );
}
