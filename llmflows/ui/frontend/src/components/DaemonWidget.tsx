import { useState, useEffect, useCallback } from "react";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";

export function DaemonWidget() {
  const [running, setRunning] = useState(false);
  const [pid, setPid] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [showStopConfirm, setShowStopConfirm] = useState(false);

  const checkStatus = useCallback(async () => {
    try {
      const data = await api.getDaemonStatus();
      setRunning(data.running);
      setPid(data.pid);
    } catch {
      setRunning(false);
      setPid(null);
    }
  }, []);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  useInterval(checkStatus, 10000);

  const loadLogs = useCallback(async () => {
    try {
      const data = await api.getDaemonLogs(300);
      setLogLines(data.lines || []);
    } catch {
      setLogLines(["Failed to load logs"]);
    }
  }, []);

  useInterval(loadLogs, showLogs ? 3000 : null);

  const toggleLogs = () => {
    const next = !showLogs;
    setShowLogs(next);
    if (next) loadLogs();
  };

  const startDaemon = async () => {
    setBusy(true);
    try {
      const result = await api.startDaemon();
      setRunning(result.running);
      setPid(result.pid);
    } catch (e) {
      console.error("Failed to start daemon:", e);
    }
    setBusy(false);
  };

  const stopDaemon = async () => {
    setShowStopConfirm(false);
    setBusy(true);
    try {
      const result = await api.stopDaemon();
      setRunning(result.running);
      setPid(result.pid);
    } catch (e) {
      console.error("Failed to stop daemon:", e);
    }
    setBusy(false);
  };

  return (
    <div className="border-t border-gray-800 px-4 py-3">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${running ? "bg-green-400" : "bg-red-400"}`} />
          <span className={`text-xs font-medium ${running ? "text-green-400" : "text-red-400"}`}>
            {running ? "Daemon running" : "Daemon stopped"}
          </span>
        </div>
        {running && pid && <span className="text-[10px] text-gray-600 font-mono">pid {pid}</span>}
      </div>
      <div className="flex items-center gap-2">
        <button onClick={toggleLogs} className="text-[11px] text-gray-500 hover:text-gray-300 transition">
          {showLogs ? "Hide logs" : "Logs"}
        </button>
        <span className="text-gray-700">&middot;</span>
        {running ? (
          <button
            onClick={() => setShowStopConfirm(true)}
            disabled={busy}
            className={`text-[11px] text-gray-500 hover:text-red-400 transition ${busy ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            {busy ? "Stopping..." : "Stop"}
          </button>
        ) : (
          <button
            onClick={startDaemon}
            disabled={busy}
            className={`text-[11px] text-gray-500 hover:text-green-400 transition ${busy ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            {busy ? "Starting..." : "Start"}
          </button>
        )}
      </div>

      {/* Daemon Logs Modal */}
      {showLogs && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
          onClick={() => setShowLogs(false)}
        >
          <div
            className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-3xl max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
              <h2 className="text-sm font-semibold">Daemon Logs</h2>
              <div className="flex items-center gap-3">
                <button onClick={loadLogs} className="text-xs text-blue-400 hover:text-blue-300">
                  Refresh
                </button>
                <button onClick={() => setShowLogs(false)} className="text-xs text-gray-500 hover:text-gray-300">
                  Close
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4 font-mono text-xs text-gray-400 whitespace-pre-wrap bg-gray-950 rounded-b-2xl">
              {logLines.map((line, i) => (
                <div key={i} className="leading-5">
                  {line}
                </div>
              ))}
              {logLines.length === 0 && <div className="text-gray-600 italic">No logs available</div>}
            </div>
          </div>
        </div>
      )}

      {/* Stop Confirmation Modal */}
      {showStopConfirm && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
          onClick={() => setShowStopConfirm(false)}
        >
          <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold mb-2">Stop Daemon?</h2>
            <p className="text-xs text-gray-400 mb-4">
              Pending runs will not be picked up while the daemon is stopped.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowStopConfirm(false)}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition"
              >
                Cancel
              </button>
              <button
                onClick={stopDaemon}
                className="px-3 py-1.5 text-xs bg-red-600 text-white rounded-lg hover:bg-red-500 transition"
              >
                Stop
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
