import { useState, useEffect } from "react";
import { api } from "@/api/client";

export function SettingsView() {
  const [pollInterval, setPollInterval] = useState(30);
  const [runTimeout, setRunTimeout] = useState(60);
  const [gateTimeout, setGateTimeout] = useState(60);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const config = await api.getDaemonConfig();
        setPollInterval(config.poll_interval_seconds ?? 30);
        setRunTimeout(config.run_timeout_minutes ?? 60);
        setGateTimeout(config.gate_timeout_seconds ?? 60);
      } catch (e) {
        console.error("Failed to load settings:", e);
      }
      setLoading(false);
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.updateDaemonConfig({
        poll_interval_seconds: pollInterval,
        run_timeout_minutes: runTimeout,
        gate_timeout_seconds: gateTimeout,
      });
      setPollInterval(updated.poll_interval_seconds);
      setRunTimeout(updated.run_timeout_minutes);
      setGateTimeout(updated.gate_timeout_seconds);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      console.error("Failed to save daemon config:", e);
    }
    setSaving(false);
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-6">Settings</h2>

      {loading && <div className="text-gray-500">Loading...</div>}

      {!loading && (
        <div className="max-w-2xl">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-medium mb-2">Daemon Configuration</h3>

            <div>
              <label className="text-xs text-gray-500 block mb-1">Poll Interval (seconds)</label>
              <input
                type="number"
                value={pollInterval}
                onChange={(e) => setPollInterval(parseInt(e.target.value) || 0)}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="text-xs text-gray-500 block mb-1">Run Timeout (minutes)</label>
              <input
                type="number"
                value={runTimeout}
                onChange={(e) => setRunTimeout(parseInt(e.target.value) || 0)}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="text-xs text-gray-500 block mb-1">Gate Timeout (seconds)</label>
              <input
                type="number"
                value={gateTimeout}
                onChange={(e) => setGateTimeout(parseInt(e.target.value) || 0)}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-2 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-40"
              >
                {saving ? "Saving..." : "Save"}
              </button>
              {saved && <span className="text-xs text-green-400">Saved</span>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
