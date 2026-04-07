import { useState, useEffect } from "react";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import type { Project, Integration } from "@/api/types";

export function IntegrationsView() {
  const [token, setToken] = useState("");
  const [maskedToken, setMaskedToken] = useState("");
  const [hasToken, setHasToken] = useState(false);
  const [tokenSaved, setTokenSaved] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [integrations, setIntegrations] = useState<Record<string, Integration | null>>({});
  const [loading, setLoading] = useState(true);

  const loadToken = async () => {
    try {
      const data = await api.getGitHubConfig();
      setHasToken(data.has_token);
      setMaskedToken(data.masked_token || "");
    } catch { /* ignore */ }
  };

  const loadProjects = async () => {
    try {
      const ps = await api.listProjects();
      setProjects(ps);
      const intMap: Record<string, Integration | null> = {};
      for (const p of ps) {
        const intgs = await api.listIntegrations(p.id);
        intMap[p.id] = intgs.find((i) => i.provider === "github") || null;
      }
      setIntegrations(intMap);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      await Promise.all([loadToken(), loadProjects()]);
      setLoading(false);
    })();
  }, []);

  useInterval(loadProjects, 15000);

  const saveToken = async () => {
    await api.updateGitHubToken(token);
    setTokenSaved(true);
    setToken("");
    loadToken();
    setTimeout(() => setTokenSaved(false), 3000);
  };

  const toggleEnabled = async (projectId: string) => {
    const intg = integrations[projectId];
    if (intg) {
      await api.updateIntegration(intg.id, { enabled: !intg.enabled });
    } else {
      await api.createIntegration(projectId, { provider: "github", config: {} });
    }
    loadProjects();
  };

  const detectRepo = async (projectId: string) => {
    let intg = integrations[projectId];
    if (!intg) {
      await api.createIntegration(projectId, { provider: "github", config: {} });
      await loadProjects();
      intg = integrations[projectId];
    }
    if (!intg) return;
    try {
      await api.detectRepo(intg.id);
      loadProjects();
    } catch (e) {
      console.error("Failed to detect repo:", e);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-xl font-semibold mb-6">GitHub Integration</h2>

      {loading && <div className="text-gray-500">Loading...</div>}

      {/* Token section */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
        <h3 className="text-sm font-medium mb-3">GitHub Token</h3>
        <div className="space-y-2">
          {hasToken && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-green-400">Token configured</span>
              <span className="text-gray-600 font-mono">{maskedToken}</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              type="password"
              placeholder={hasToken ? "Replace token..." : "Enter GitHub token"}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={saveToken}
              disabled={!token.trim()}
              className="px-4 py-2 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-40"
            >
              Save
            </button>
          </div>
          {tokenSaved && <span className="text-xs text-green-400">Token saved</span>}
        </div>
      </div>

      {/* Per-project integrations */}
      <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Projects</h3>
      <div className="space-y-2">
        {projects.map((p) => {
          const intg = integrations[p.id];
          const repo = intg?.config?.repo || "";
          const lastPolled = intg?.last_polled_at ? new Date(intg.last_polled_at).toLocaleString() : "Never";

          return (
            <div key={p.id} className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <h4 className="text-sm font-medium text-white">{p.name}</h4>
                  {repo && <span className="text-xs text-gray-500 font-mono">{repo}</span>}
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => detectRepo(p.id)}
                    className="text-xs text-gray-500 hover:text-gray-300"
                  >
                    Detect Repo
                  </button>
                  <button
                    onClick={() => toggleEnabled(p.id)}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                      intg?.enabled ? "bg-blue-600" : "bg-gray-700"
                    }`}
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                        intg?.enabled ? "translate-x-4" : "translate-x-1"
                      }`}
                    />
                  </button>
                </div>
              </div>
              {intg && (
                <div className="mt-1 text-xs text-gray-600">
                  Last polled: {lastPolled}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
