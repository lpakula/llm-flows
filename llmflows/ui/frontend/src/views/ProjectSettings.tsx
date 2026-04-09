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
  const [settings, setSettings] = useState<ProjectSettings>({ is_git_repo: true });
  const [loading, setLoading] = useState(true);

  const [nameValue, setNameValue] = useState("");
  const [nameDirty, setNameDirty] = useState(false);
  const [nameSaving, setNameSaving] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);

  const [gitSaving, setGitSaving] = useState(false);
  const [gitSaved, setGitSaved] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const [p, s] = await Promise.all([
          api.getProject(projectId),
          api.getProjectSettings(projectId),
        ]);
        setProject(p);
        setSettings(s);
        setNameValue(p.name);
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

  const toggleGitRepo = async () => {
    if (!projectId) return;
    const next = !settings.is_git_repo;
    setSettings({ ...settings, is_git_repo: next });
    setGitSaving(true);
    try {
      const updated = await api.updateProjectSettings(projectId, { is_git_repo: next });
      setSettings(updated);
      setGitSaved(true);
      setTimeout(() => setGitSaved(false), 2000);
    } catch (e) {
      console.error("Failed to update project settings:", e);
      setSettings({ ...settings, is_git_repo: !next });
    }
    setGitSaving(false);
  };

  const deleteProject = async () => {
    if (!project || !confirm(`Delete project "${project.name}"? All tasks and runs will be lost.`)) return;
    await api.deleteProject(project.id);
    reloadApp();
    navigate("/");
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
          &larr; Back to tasks
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

            {/* Git repo */}
            <tr className="bg-gray-900">
              <td className="px-4 py-3 font-medium text-white whitespace-nowrap">Git Repository</td>
              <td className="px-4 py-3 text-xs hidden md:table-cell">
                <span className="text-gray-500">When enabled, agents run in isolated worktree branches. </span>
                {!settings.is_git_repo && (
                  <span className="text-yellow-400">Agents run directly in the project directory.</span>
                )}
              </td>
              <td className="px-4 py-3">
                <button
                  onClick={toggleGitRepo}
                  disabled={gitSaving}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${settings.is_git_repo ? "bg-blue-600" : "bg-gray-700"}`}
                >
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${settings.is_git_repo ? "translate-x-4" : "translate-x-1"}`} />
                </button>
              </td>
              <td className="px-4 py-3 text-right">
                {gitSaved && <span className="text-xs text-green-400">Saved</span>}
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
            <p className="text-xs text-gray-500 mt-0.5">All tasks, runs, and flows associated with this project will be permanently deleted.</p>
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
