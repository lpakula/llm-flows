function asUTC(iso: string): string {
  return iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z";
}

export function duration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt) return "-";
  const start = new Date(asUTC(startedAt));
  const end = completedAt ? new Date(asUTC(completedAt)) : new Date();
  const ms = end.getTime() - start.getTime();
  return formatSeconds(ms / 1000);
}

export function formatSeconds(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null) return "-";
  if (totalSeconds < 1) return "<1s";
  const s = Math.floor(totalSeconds);
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return m + "m " + rs + "s";
  const h = Math.floor(m / 60);
  return h + "h " + (m % 60) + "m";
}

export function statusBadge(status: string): string {
  return (
    ({
      queued: "bg-blue-900/50 text-blue-300",
      running: "bg-yellow-900/50 text-yellow-300",
      awaiting_user: "bg-amber-900/50 text-amber-300",
      paused: "bg-purple-900/50 text-purple-300",
      completed: "bg-green-900/50 text-green-300",
      cancelled: "bg-red-900/50 text-red-400",
      failed: "bg-red-900/50 text-red-300",
      interrupted: "bg-red-900/50 text-red-300",
      error: "bg-red-900/50 text-red-300",
      timeout: "bg-orange-900/50 text-orange-300",
      idle: "bg-gray-700 text-gray-300",
    } as Record<string, string>)[status] || "bg-gray-700 text-gray-300"
  );
}

export function statusDot(status: string, outcome?: string | null): string {
  if (status === "running") return "bg-yellow-400 animate-pulse";
  if (status === "awaiting_user") return "bg-amber-400 animate-pulse";
  if (status === "paused") return "bg-purple-400";
  if (status === "queued") return "bg-blue-400";
  if (status === "interrupted" || status === "error" || status === "cancelled") return "bg-red-500";
  if (status === "timeout") return "bg-orange-400";
  if (status === "completed") {
    if (outcome === "failed") return "bg-red-500";
    if (outcome === "cancelled") return "bg-red-400";
    return "bg-green-500";
  }
  return "bg-gray-500";
}

export function displayStatus(run: { status: string; outcome: string | null }): string {
  if (run.status === "completed" && run.outcome && run.outcome !== "completed") {
    return run.outcome;
  }
  if (run.status === "awaiting_user") return "waiting";
  return run.status;
}

export function stepBoxClass(status: string): string {
  return (
    ({
      completed: "bg-green-900/40 border-green-700 text-green-400",
      running: "bg-yellow-900/40 border-yellow-600 text-yellow-300 font-semibold",
      current: "bg-yellow-900/40 border-yellow-600 text-yellow-300 font-semibold",
      awaiting_user: "bg-amber-900/40 border-amber-600 text-amber-300 font-semibold",
      paused: "bg-purple-900/40 border-purple-700 text-purple-400",
      manual: "bg-blue-900/40 border-blue-700 text-blue-400",
      skipped: "bg-gray-900/30 border-gray-800 text-gray-600",
      pending: "bg-gray-900/50 border-gray-700 text-gray-500",
      failed: "bg-red-900/40 border-red-700 text-red-400",
      timeout: "bg-orange-900/40 border-orange-700 text-orange-400",
      error: "bg-red-900/40 border-red-700 text-red-400",
    } as Record<string, string>)[status] || "bg-gray-900/50 border-gray-700 text-gray-500"
  );
}

export function stepConnectorClass(status: string): string {
  return (
    ({
      completed: "bg-green-700",
      running: "bg-yellow-600",
      current: "bg-yellow-600",
      awaiting_user: "bg-amber-600",
      skipped: "bg-gray-800",
      pending: "bg-gray-800",
    } as Record<string, string>)[status] || "bg-gray-800"
  );
}
