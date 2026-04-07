import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { useApp } from "@/App";
import type { Project, Task, Flow, ProjectSettings as PS } from "@/api/types";
import { typeColor } from "@/lib/format";

export function ProjectView() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { reload: reloadApp, flows: globalFlows } = useApp();

  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newTask, setNewTask] = useState({ title: "", description: "", type: "feature" });
  const [editingName, setEditingName] = useState(false);
  const [editName, setEditName] = useState("");
  const [settings, setSettings] = useState<PS>({ is_git_repo: true });
  const [showSettings, setShowSettings] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const [p, t, a, s] = await Promise.all([
        api.getProject(projectId),
        api.listTasks(projectId),
        api.listAgents(),
        api.getProjectSettings(projectId),
      ]);
      setProject(p);
      setTasks(t);
      setAgents(a);
      setSettings(s);
      const da = p.aliases?.["default"];
      if (da?.agent) {
        const m = await api.listModels(da.agent);
        setModels(m);
      }
    } catch (e) {
      console.error("Project load error:", e);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);
  useInterval(load, 5000);

  const createTask = async () => {
    if (!projectId) return;
    await api.createTask(projectId, newTask);
    setNewTask({ title: "", description: "", type: "feature" });
    setShowCreate(false);
    load();
  };

  const renameProject = async () => {
    if (!editName.trim() || !project) return;
    await api.updateProject(project.id, { name: editName.trim() });
    setEditingName(false);
    load();
    reloadApp();
  };

  const deleteProject = async () => {
    if (!project || !confirm(`Delete project "${project.name}"? All tasks and runs will be lost.`)) return;
    await api.deleteProject(project.id);
    reloadApp();
    navigate("/");
  };

  const deleteTask = async (taskId: string) => {
    if (!confirm("Delete this task?")) return;
    await api.deleteTask(taskId);
    load();
  };

  const toggleGitRepo = async () => {
    if (!projectId) return;
    const next = !settings.is_git_repo;
    setSettings({ ...settings, is_git_repo: next });
    await api.updateProjectSettings(projectId, { is_git_repo: next });
  };

  const sortedTasks = [...tasks].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {!editingName ? (
              <>
                <h2 className="text-base font-medium">{project?.name || "Loading..."}</h2>
                <span className="text-xs text-gray-500">{project?.path || ""}</span>
                <button
                  onClick={() => {
                    setEditName(project?.name || "");
                    setEditingName(true);
                  }}
                  className="text-xs text-gray-500 hover:text-blue-400 transition"
                >
                  Rename
                </button>
                <button onClick={deleteProject} className="text-xs text-gray-500 hover:text-red-400 transition">
                  Delete
                </button>
              </>
            ) : (
              <>
                <input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") renameProject();
                    if (e.key === "Escape") setEditingName(false);
                  }}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-64"
                  autoFocus
                />
                <button onClick={renameProject} className="text-xs text-blue-400 hover:text-blue-300">
                  Save
                </button>
                <button onClick={() => setEditingName(false)} className="text-xs text-gray-500 hover:text-gray-300">
                  Cancel
                </button>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={`text-sm px-4 py-1.5 rounded-lg border transition ${
                showSettings
                  ? "border-blue-500 text-blue-400 bg-blue-950/40"
                  : "border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600"
              }`}
            >
              Configure
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition"
            >
              + New Task
            </button>
          </div>
        </div>

        {showSettings && (
          <div className="mt-3 pt-3 border-t border-gray-800">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">Git repo</span>
              <button
                onClick={toggleGitRepo}
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                  settings.is_git_repo ? "bg-blue-600" : "bg-gray-700"
                }`}
              >
                <span
                  className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                    settings.is_git_repo ? "translate-x-4" : "translate-x-1"
                  }`}
                />
              </button>
              <span className={`text-xs ${settings.is_git_repo ? "text-green-400" : "text-yellow-400"}`}>
                {settings.is_git_repo ? "yes" : "no"}
              </span>
            </div>
            {!settings.is_git_repo && (
              <p className="mt-2 text-xs text-yellow-400/80">
                Worktrees and task branches are disabled. The agent will run directly in the project
                directory without git isolation.
              </p>
            )}
          </div>
        )}
      </header>

      {/* Create Task Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold mb-4">New Task</h2>
            <div className="space-y-3">
              <input
                value={newTask.title}
                onChange={(e) => setNewTask({ ...newTask, title: e.target.value })}
                placeholder="Task title"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoFocus
              />
              <textarea
                value={newTask.description}
                onChange={(e) => setNewTask({ ...newTask, description: e.target.value })}
                placeholder="Description (optional)"
                rows={3}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
              <select
                value={newTask.type}
                onChange={(e) => setNewTask({ ...newTask, type: e.target.value })}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="feature">Feature</option>
                <option value="fix">Fix</option>
                <option value="refactor">Refactor</option>
                <option value="chore">Chore</option>
              </select>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200">
                Cancel
              </button>
              <button
                onClick={createTask}
                disabled={!newTask.title.trim()}
                className="px-4 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-40"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Task List */}
      <div className="p-6">
        {sortedTasks.length === 0 && !showCreate && (
          <div className="text-gray-500 text-center py-8">No tasks yet</div>
        )}
        <div className="space-y-2">
          {sortedTasks.map((task) => (
            <div
              key={task.id}
              className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-3 flex items-center justify-between hover:border-gray-600 transition cursor-pointer"
              onClick={() => navigate(`/task/${task.id}`)}
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className={`text-[10px] uppercase font-medium ${typeColor(task.type)}`}>
                  {task.type}
                </span>
                <span className="text-sm text-white truncate">{task.name}</span>
                {task.run_count > 0 && (
                  <span className="text-xs text-gray-500">{task.run_count} runs</span>
                )}
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                {task.agent_active && (
                  <span className="flex items-center gap-1 text-xs text-yellow-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
                    Running
                  </span>
                )}
                {task.flow && (
                  <span className="text-xs text-cyan-400">{task.flow}</span>
                )}
                {task.current_step && (
                  <span className="text-xs text-gray-500">
                    {task.current_step === "__one_shot__" ? "one-shot" : task.current_step === "__summary__" ? "summary" : task.current_step}
                  </span>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteTask(task.id);
                  }}
                  className="text-xs text-gray-600 hover:text-red-400 transition"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
