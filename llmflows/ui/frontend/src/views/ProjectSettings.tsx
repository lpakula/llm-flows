import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useApp } from "@/App";
import type { Project, ProjectSettings } from "@/api/types";

export function ProjectSettingsView() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { reload: reloadApp } = useApp();

  const [project, setProject] = useState<Project | null>(null);
  const [settings, setSettings] = useState<ProjectSettings>({ is_git_repo: true, max_concurrent_tasks: 1 });
  const [loading, setLoading] = useState(true);

  const [nameValue, setNameValue] = useState("");
  const [nameDirty, setNameDirty] = useState(false);
  const [nameSaving, setNameSaving] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);

  const [concurrencyValue, setConcurrencyValue] = useState(1);
  const [concurrencyDirty, setConcurrencyDirty] = useState(false);
  const [concurrencySaving, setConcurrencySaving] = useState(false);
  const [concurrencySaved, setConcurrencySaved] = useState(false);

  const [variables, setVariables] = useState<Record<string, string>>({});
  const [newVarKey, setNewVarKey] = useState("");
  const [newVarValue, setNewVarValue] = useState("");
  const [varSaving, setVarSaving] = useState<string | null>(null);
  const [editingVar, setEditingVar] = useState<{ key: string; value: string } | null>(null);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const [p, s, v] = await Promise.all([
          api.getProject(projectId),
          api.getProjectSettings(projectId),
          api.getProjectVariables(projectId),
        ]);
        setProject(p);
        setSettings(s);
        setVariables(v);
        setNameValue(p.name);
        setConcurrencyValue(s.max_concurrent_tasks ?? 1);
      } catch (e) {
        console.error("Failed to load project settings:", e);
      }
      setLoading(false);
    })();
  }, [projectId]);

  const saveName = async () => {
    if (!project || !nameValue.trim()) return;
    setNameSaving(true);
    try {
      const updated = await api.updateProject(project.id, { name: nameValue.trim() });
      setProject(updated);
      setNameDirty(false);
      setNameSaved(true);
      setTimeout(() => setNameSaved(false), 2000);
      reloadApp();
    } catch (e) {
      console.error("Failed to rename project:", e);
    }
    setNameSaving(false);
  };

  const saveConcurrency = async () => {
    if (!projectId) return;
    const val = Math.max(1, concurrencyValue);
    setConcurrencySaving(true);
    try {
      const updated = await api.updateProjectSettings(projectId, { max_concurrent_tasks: val });
      setSettings(updated);
      setConcurrencyValue(updated.max_concurrent_tasks ?? val);
      setConcurrencyDirty(false);
      setConcurrencySaved(true);
      setTimeout(() => setConcurrencySaved(false), 2000);
    } catch (e) {
      console.error("Failed to update concurrency:", e);
    }
    setConcurrencySaving(false);
  };

  const deleteProject = async () => {
    if (!project || !confirm(`Delete project "${project.name}"? All runs and flows will be lost.`)) return;
    await api.deleteProject(project.id);
    reloadApp();
    navigate("/");
  };

  const addVariable = async () => {
    if (!projectId || !newVarKey.trim()) return;
    setVarSaving(newVarKey);
    try {
      const updated = await api.setProjectVariable(projectId, newVarKey.trim(), newVarValue);
      setVariables(updated);
      setNewVarKey("");
      setNewVarValue("");
    } catch (e) {
      console.error("Failed to set variable:", e);
    }
    setVarSaving(null);
  };

  const saveEditingVar = async () => {
    if (!projectId || !editingVar) return;
    setVarSaving(editingVar.key);
    try {
      const updated = await api.setProjectVariable(projectId, editingVar.key, editingVar.value);
      setVariables(updated);
      setEditingVar(null);
    } catch (e) {
      console.error("Failed to update variable:", e);
    }
    setVarSaving(null);
  };

  const removeVariable = async (key: string) => {
    if (!projectId) return;
    setVarSaving(key);
    try {
      const updated = await api.deleteProjectVariable(projectId, key);
      setVariables(updated);
    } catch (e) {
      console.error("Failed to remove variable:", e);
    }
    setVarSaving(null);
  };

  if (loading) {
    return <div className="flex-1 overflow-y-auto p-6 text-gray-500">Loading...</div>;
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mb-6">
        <button
          onClick={() => navigate(`/project/${projectId}`)}
          className="text-xs text-gray-500 hover:text-gray-300 mb-3 block"
        >
          &larr; Back to board
        </button>
        <h2 className="text-xl font-semibold">Project Settings</h2>
        {project && (
          <p className="text-xs text-gray-500 mt-1 font-mono">{project.path}</p>
        )}
      </div>

      {/* Settings table */}
      <div className="border border-gray-800 rounded-xl overflow-hidden mb-8">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/60">
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Setting</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden md:table-cell">Description</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Value</th>
              <th className="px-4 py-3 w-20"></th>
            </tr>
          </thead>
          <tbody>
            {/* Name */}
            <tr className="bg-gray-900 border-b border-gray-800">
              <td className="px-4 py-3 font-medium text-white whitespace-nowrap">Name</td>
              <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">Display name for this project</td>
              <td className="px-4 py-3">
                <input
                  value={nameValue}
                  onChange={(e) => { setNameValue(e.target.value); setNameDirty(true); }}
                  onKeyDown={(e) => e.key === "Enter" && saveName()}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-64 focus:outline-none focus:border-gray-500"
                />
              </td>
              <td className="px-4 py-3 text-right">
                {nameSaved ? (
                  <span className="text-xs text-green-400">Saved</span>
                ) : (
                  <button
                    onClick={saveName}
                    disabled={!nameDirty || nameSaving || !nameValue.trim()}
                    className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                  >
                    {nameSaving ? "Saving…" : "Save"}
                  </button>
                )}
              </td>
            </tr>

            {/* Max concurrent tasks */}
            <tr className="bg-gray-900 border-b border-gray-800">
              <td className="px-4 py-3 font-medium text-white whitespace-nowrap">Max Concurrent Runs</td>
              <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">How many flow runs can be in progress at the same time</td>
              <td className="px-4 py-3">
                <input
                  type="number"
                  min={1}
                  value={concurrencyValue}
                  onChange={(e) => { setConcurrencyValue(parseInt(e.target.value) || 1); setConcurrencyDirty(true); }}
                  onKeyDown={(e) => e.key === "Enter" && saveConcurrency()}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-20 focus:outline-none focus:border-gray-500"
                />
              </td>
              <td className="px-4 py-3 text-right">
                {concurrencySaved ? (
                  <span className="text-xs text-green-400">Saved</span>
                ) : (
                  <button
                    onClick={saveConcurrency}
                    disabled={!concurrencyDirty || concurrencySaving}
                    className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                  >
                    {concurrencySaving ? "Saving..." : "Save"}
                  </button>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Variables */}
      <div className="border border-gray-800 rounded-xl overflow-hidden mb-8">
        <div className="px-4 py-3 bg-gray-900/60 border-b border-gray-800 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium text-white">Variables</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Available in flow steps, gates, and IFs as <code className="text-gray-400">{"{{project.<KEY>}}"}</code>. Injected as environment variables into the agent runtime.
            </p>
          </div>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/40">
              <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide w-1/3">Key</th>
              <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Value</th>
              <th className="px-4 py-2 w-24"></th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(variables).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => (
              <tr key={key} className="bg-gray-900 border-b border-gray-800">
                <td className="px-4 py-2.5 font-mono text-xs text-cyan-400">{key}</td>
                <td className="px-4 py-2.5">
                  {editingVar?.key === key ? (
                    <input
                      value={editingVar.value}
                      onChange={(e) => setEditingVar({ ...editingVar, value: e.target.value })}
                      onKeyDown={(e) => { if (e.key === "Enter") saveEditingVar(); if (e.key === "Escape") setEditingVar(null); }}
                      autoFocus
                      className="bg-gray-800 border border-gray-600 rounded px-2 py-0.5 text-xs font-mono w-full focus:outline-none focus:border-blue-500"
                    />
                  ) : (
                    <span
                      className="text-xs font-mono text-gray-300 cursor-pointer hover:text-white"
                      onClick={() => setEditingVar({ key, value })}
                      title="Click to edit"
                    >
                      {value}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right whitespace-nowrap">
                  {editingVar?.key === key ? (
                    <span className="space-x-2">
                      <button
                        onClick={saveEditingVar}
                        disabled={varSaving === key}
                        className="text-xs text-blue-400 hover:text-blue-300"
                      >
                        {varSaving === key ? "Saving…" : "Save"}
                      </button>
                      <button
                        onClick={() => setEditingVar(null)}
                        className="text-xs text-gray-500 hover:text-gray-300"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => removeVariable(key)}
                      disabled={varSaving === key}
                      className="text-xs text-red-400/60 hover:text-red-400 transition-colors"
                    >
                      {varSaving === key ? "…" : "Remove"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {/* Add new variable row */}
            <tr className="bg-gray-900/50">
              <td className="px-4 py-2.5">
                <input
                  value={newVarKey}
                  onChange={(e) => setNewVarKey(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addVariable()}
                  placeholder="KEY"
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs font-mono w-full focus:outline-none focus:border-gray-500 placeholder:text-gray-600"
                />
              </td>
              <td className="px-4 py-2.5">
                <input
                  value={newVarValue}
                  onChange={(e) => setNewVarValue(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addVariable()}
                  placeholder="value"
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs font-mono w-full focus:outline-none focus:border-gray-500 placeholder:text-gray-600"
                />
              </td>
              <td className="px-4 py-2.5 text-right">
                <button
                  onClick={addVariable}
                  disabled={!newVarKey.trim() || varSaving !== null}
                  className="text-xs text-blue-400 disabled:opacity-30 hover:text-blue-300 transition-colors"
                >
                  Add
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Danger zone */}
      <div className="border border-red-900/50 rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-red-950/20 border-b border-red-900/50">
          <h3 className="text-sm font-medium text-red-400">Danger zone</h3>
        </div>
        <div className="px-4 py-4 bg-gray-900 flex items-center justify-between">
          <div>
            <p className="text-sm text-white">Delete this project</p>
            <p className="text-xs text-gray-500 mt-0.5">All flow runs and flows associated with this project will be permanently deleted.</p>
          </div>
          <button
            onClick={deleteProject}
            className="ml-6 px-4 py-1.5 text-xs bg-red-700 hover:bg-red-600 text-white rounded-lg transition-colors shrink-0"
          >
            Delete project
          </button>
        </div>
      </div>
    </div>
  );
}
