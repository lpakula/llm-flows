import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { RunnerImageStatus } from "@/api/types";

const defaultRunner: RunnerImageStatus = {
  tag: "llmflows:unknown",
  exists: false,
  building: false,
  error: null,
  docker_available: false,
};

export function DaemonWidget() {
  const [running, setRunning] = useState(false);
  const [pid, setPid] = useState<number | null>(null);
  const [runner, setRunner] = useState<RunnerImageStatus>(defaultRunner);
  const [busy, setBusy] = useState(false);
  const [buildBusy, setBuildBusy] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [showBuildLogs, setShowBuildLogs] = useState(false);
  const [buildLogLines, setBuildLogLines] = useState<string[]>([]);
  const [showCancelBuildConfirm, setShowCancelBuildConfirm] = useState(false);
  const [cancelBuildBusy, setCancelBuildBusy] = useState(false);
  const buildLogEndRef = useRef<HTMLDivElement>(null);
  const [showStopConfirm, setShowStopConfirm] = useState(false);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [killResult, setKillResult] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      const data = await api.getDaemonStatus();
      setRunning(data.running);
      setPid(data.pid);
      setRunner(data.runner ?? defaultRunner);
    } catch {
      setRunning(false);
      setPid(null);
    }
  }, []);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  useInterval(checkStatus, runner.building ? 3000 : 10000);

  const loadLogs = useCallback(async () => {
    try {
      const data = await api.getDaemonLogs(300);
      setLogLines(data.lines || []);
    } catch {
      setLogLines(["Failed to load logs"]);
    }
  }, []);

  useInterval(loadLogs, showLogs ? 3000 : null);

  const loadBuildLogs = useCallback(async () => {
    try {
      const data = await api.getRunnerBuildLogs(500);
      setBuildLogLines(data.lines || []);
    } catch {
      setBuildLogLines(["Failed to load build logs"]);
    }
  }, []);

  useInterval(loadBuildLogs, showBuildLogs ? (runner.building ? 1500 : 3000) : null);

  useEffect(() => {
    if (showBuildLogs) {
      buildLogEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [buildLogLines, showBuildLogs]);

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
      if (result.runner) setRunner(result.runner);
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
      if (result.runner) setRunner(result.runner);
    } catch (e) {
      console.error("Failed to stop daemon:", e);
    }
    setBusy(false);
  };

  const buildRunnerImage = async () => {
    setBuildBusy(true);
    try {
      await api.buildRunnerImage();
      setRunner((prev) => ({ ...prev, building: true, error: null }));
      setShowBuildLogs(true);
      await loadBuildLogs();
      await checkStatus();
    } catch (e) {
      console.error("Failed to start runner image build:", e);
    }
    setBuildBusy(false);
  };

  const openBuildLogs = () => {
    setShowBuildLogs(true);
    loadBuildLogs();
  };

  const cancelRunnerBuild = async () => {
    setShowCancelBuildConfirm(false);
    setCancelBuildBusy(true);
    try {
      await api.cancelRunnerBuild();
      await loadBuildLogs();
      await checkStatus();
    } catch (e) {
      console.error("Failed to cancel runner build:", e);
    }
    setCancelBuildBusy(false);
  };

  const killAll = async () => {
    setShowKillConfirm(false);
    setBusy(true);
    try {
      const result = await api.killAllAgents();
      setKillResult(`Killed ${result.killed} process(es), cancelled ${result.runs_cancelled ?? 0} run(s)`);
      setTimeout(() => setKillResult(null), 5000);
    } catch (e) {
      console.error("Failed to kill agents:", e);
      setKillResult("Failed to kill agents");
      setTimeout(() => setKillResult(null), 5000);
    }
    setBusy(false);
    checkStatus();
  };

  const runnerReady = runner.exists;
  const runnerLabel = runner.building
    ? "Building…"
    : runnerReady
      ? "Ready"
      : runner.docker_available
        ? "Missing"
        : "No Docker";

  const runnerColor = runner.building
    ? "text-yellow-400"
    : runnerReady
      ? "text-green-400"
      : "text-red-400";

  const runnerDot = runner.building
    ? "bg-yellow-400"
    : runnerReady
      ? "bg-green-400"
      : "bg-red-400";

  const canShowBuildLogs =
    runner.building || !!runner.error || (!runnerReady && runner.docker_available);

  return (
    <div className="border-t border-gray-800 px-4 py-3">
      <div className="flex items-center justify-between gap-2 mb-1 min-w-0 whitespace-nowrap">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`w-2 h-2 rounded-full shrink-0 ${running ? "bg-green-400" : "bg-red-400"}`} />
          <span className={`text-xs font-medium truncate ${running ? "text-green-400" : "text-red-400"}`}>
            {running ? "Daemon running" : "Daemon stopped"}
          </span>
        </div>
        {running && pid && (
          <span className="text-[10px] text-gray-600 font-mono shrink-0">pid {pid}</span>
        )}
      </div>
      <div
        className={`flex items-center justify-between gap-2 mb-2 min-w-0 whitespace-nowrap rounded -mx-1 px-1 ${
          canShowBuildLogs ? "cursor-pointer hover:bg-gray-800/50" : ""
        }`}
        onClick={canShowBuildLogs ? openBuildLogs : undefined}
        onKeyDown={
          canShowBuildLogs
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") openBuildLogs();
              }
            : undefined
        }
        role={canShowBuildLogs ? "button" : undefined}
        tabIndex={canShowBuildLogs ? 0 : undefined}
        title={canShowBuildLogs ? "View build logs" : runner.tag}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`w-2 h-2 rounded-full shrink-0 ${runnerDot}`} />
          <span className={`text-xs font-medium truncate ${runnerColor}`}>{runnerLabel}</span>
        </div>
        <span className="text-[10px] text-gray-600 font-mono truncate shrink-0 max-w-[45%]">
          {runner.tag}
        </span>
      </div>
      {runner.error && (
        <p className="text-[10px] text-red-400/80 mb-2 leading-snug">{runner.error}</p>
      )}
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
        {!runnerReady && runner.docker_available && (
          <>
            <span className="text-gray-700">&middot;</span>
            <button
              onClick={buildRunnerImage}
              disabled={buildBusy || runner.building}
              className={`text-[11px] text-gray-500 hover:text-yellow-400 transition ${buildBusy || runner.building ? "opacity-40 cursor-not-allowed" : ""}`}
            >
              {runner.building ? "Building…" : buildBusy ? "Starting…" : "Build image"}
            </button>
          </>
        )}
      </div>

      {/* Runner Build Logs Modal */}
      {showBuildLogs && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
          onClick={() => setShowBuildLogs(false)}
        >
          <div
            className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-3xl max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
              <h2 className="text-sm font-semibold">
                Runner Image Build
                {runner.building && (
                  <span className="ml-2 text-xs font-normal text-yellow-400">building…</span>
                )}
              </h2>
              <div className="flex items-center gap-3">
                {runner.building && (
                  <button
                    onClick={() => setShowCancelBuildConfirm(true)}
                    disabled={cancelBuildBusy}
                    className="text-xs text-red-500 hover:text-red-400 transition disabled:opacity-40"
                  >
                    Cancel build
                  </button>
                )}
                <button onClick={loadBuildLogs} className="text-xs text-blue-400 hover:text-blue-300">
                  Refresh
                </button>
                <button
                  onClick={() => setShowBuildLogs(false)}
                  className="text-xs text-gray-500 hover:text-gray-300"
                >
                  Close
                </button>
              </div>
            </div>
            {runner.error && (
              <div className="px-5 py-2 bg-red-900/30 border-b border-red-800/50 text-xs text-red-300">
                {runner.error}
              </div>
            )}
            <div className="flex-1 overflow-y-auto p-4 font-mono text-xs text-gray-400 whitespace-pre-wrap bg-gray-950 rounded-b-2xl">
              {buildLogLines.map((line, i) => (
                <div key={i} className="leading-5">
                  {line}
                </div>
              ))}
              {buildLogLines.length === 0 && (
                <div className="text-gray-600 italic">
                  {runner.building ? "Waiting for build output…" : "No build logs available"}
                </div>
              )}
              <div ref={buildLogEndRef} />
            </div>
          </div>
        </div>
      )}

      {/* Cancel Build Confirmation Modal */}
      {showCancelBuildConfirm && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
          onClick={() => setShowCancelBuildConfirm(false)}
        >
          <div
            className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-sm p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-sm font-semibold mb-2">Cancel Image Build?</h2>
            <p className="text-xs text-gray-400 mb-4">
              This stops the current Docker build. You can start it again from the status panel.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowCancelBuildConfirm(false)}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition"
              >
                Keep building
              </button>
              <button
                onClick={cancelRunnerBuild}
                className="px-3 py-1.5 text-xs bg-red-600 text-white rounded-lg hover:bg-red-500 transition"
              >
                Cancel build
              </button>
            </div>
          </div>
        </div>
      )}

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
                <button
                  onClick={() => setShowKillConfirm(true)}
                  disabled={busy}
                  className="text-xs text-red-500 hover:text-red-400 transition disabled:opacity-40"
                >
                  Kill All
                </button>
                <button onClick={loadLogs} className="text-xs text-blue-400 hover:text-blue-300">
                  Refresh
                </button>
                <button onClick={() => setShowLogs(false)} className="text-xs text-gray-500 hover:text-gray-300">
                  Close
                </button>
              </div>
            </div>
            {killResult && (
              <div className="px-5 py-2 bg-red-900/30 border-b border-red-800/50 text-xs text-red-300">
                {killResult}
              </div>
            )}
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

      {/* Kill All Confirmation Modal */}
      {showKillConfirm && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
          onClick={() => setShowKillConfirm(false)}
        >
          <div className="bg-gray-900 rounded-2xl border border-red-700/50 w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold text-red-400 mb-2">Kill All Agents?</h2>
            <p className="text-xs text-gray-400 mb-4">
              This will immediately SIGKILL all running agent processes, cancel all active runs, and stop the daemon. Use this as an emergency stop.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowKillConfirm(false)}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition"
              >
                Cancel
              </button>
              <button
                onClick={killAll}
                className="px-3 py-1.5 text-xs bg-red-600 text-white rounded-lg hover:bg-red-500 transition"
              >
                Kill All
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
