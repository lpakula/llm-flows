import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { useLogStream } from "@/hooks/useEventSource";
import { useApp } from "@/App";
import { LogViewer } from "@/components/LogViewer";
import type { Task, TaskRun, StepRunInfo, Project } from "@/api/types";
import { statusBadge, displayStatus, duration, stepBoxClass, stepConnectorClass } from "@/lib/format";

export function TaskView() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const { projects } = useApp();

  const [task, setTask] = useState<Task | null>(null);
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [runSteps, setRunSteps] = useState<Record<string, StepRunInfo[]>>({});
  const [logUrl, setLogUrl] = useState<string | null>(null);
  const [viewingStepName, setViewingStepName] = useState<string | null>(null);

  // Run modal state
  const [runModal, setRunModal] = useState(false);
  const [runModalProject, setRunModalProject] = useState<Project | null>(null);
  const [runModalAlias, setRunModalAlias] = useState("");
  const [runModalPrompt, setRunModalPrompt] = useState("");
  const [runModalOneShot, setRunModalOneShot] = useState(false);

  // Description editing
  const [editingDesc, setEditingDesc] = useState(false);
  const [editDescText, setEditDescText] = useState("");

  const worktreePrefix = task?.worktree_path ? task.worktree_path + "/" : null;
  const { entries: logEntries, streaming } = useLogStream(logUrl, worktreePrefix);

  const isRunActive = (run: TaskRun) => !!run.started_at && !run.completed_at;

  const loadTask = useCallback(async () => {
    if (!taskId) return;
    try {
      for (const p of projects) {
        const ts = await api.listTasks(p.id);
        const found = ts.find((t) => t.id === taskId);
        if (found) {
          setTask(found);
          const r = await api.listTaskRuns(taskId);
          setRuns(r);
          if (expandedRun) {
            const data = await api.getRunSteps(expandedRun);
            setRunSteps((prev) => ({ ...prev, [expandedRun]: data.steps }));
          }
          return;
        }
      }
    } catch (e) {
      console.error("Task load error:", e);
    }
  }, [taskId, projects, expandedRun]);

  useEffect(() => {
    const load = async () => {
      if (!taskId) return;
      for (const p of projects) {
        const ts = await api.listTasks(p.id);
        const found = ts.find((t) => t.id === taskId);
        if (found) {
          setTask(found);
          const r = await api.listTaskRuns(taskId);
          setRuns(r);
          const activeRun = r.find((run) => isRunActive(run));
          if (activeRun) {
            setExpandedRun(activeRun.id);
            const data = await api.getRunSteps(activeRun.id);
            setRunSteps((prev) => ({ ...prev, [activeRun.id]: data.steps }));
            const steps = data.steps;
            const activeStep = steps.find((s) => s.step_run && s.status === "running");
            if (activeStep?.step_run) {
              setLogUrl(`/api/step-runs/${activeStep.step_run.id}/logs`);
              setViewingStepName(activeStep.name);
            }
          }
          return;
        }
      }
    };
    load();
  }, [taskId, projects]);

  useInterval(loadTask, 5000);

  const loadRunSteps = async (runId: string) => {
    const data = await api.getRunSteps(runId);
    setRunSteps((prev) => ({ ...prev, [runId]: data.steps }));
  };

  const toggleRun = (runId: string) => {
    if (expandedRun === runId) {
      setExpandedRun(null);
      setLogUrl(null);
      setViewingStepName(null);
    } else {
      setExpandedRun(runId);
      loadRunSteps(runId);
      const run = runs.find((r) => r.id === runId);
      if (run && isRunActive(run)) {
        const steps = runSteps[runId] || [];
        const activeStep = steps.find((s) => s.step_run && s.status === "running");
        if (activeStep?.step_run) {
          viewStepLogs(activeStep);
        }
      }
    }
  };

  const viewStepLogs = (step: StepRunInfo) => {
    if (!step.step_run) return;
    setLogUrl(`/api/step-runs/${step.step_run.id}/logs`);
    const name = step.name === "__summary__" ? "summary" : step.name === "__one_shot__" ? "one-shot" : step.name;
    setViewingStepName(name);
  };

  const forceStopRun = async (runId: string) => {
    if (!confirm("Force stop this run? The agent process will be killed.")) return;
    await api.stopRun(runId);
    setLogUrl(null);
    if (taskId) {
      setRuns(await api.listTaskRuns(taskId));
    }
  };

  const deleteRun = async (runId: string) => {
    if (!confirm("Delete this run?")) return;
    await api.deleteRun(runId);
    if (expandedRun === runId) {
      setExpandedRun(null);
      setLogUrl(null);
    }
    if (taskId) {
      setRuns(await api.listTaskRuns(taskId));
    }
  };

  const openRunModal = async () => {
    setRunModalPrompt("");
    setRunModalAlias("");
    setRunModalOneShot(false);
    try {
      const project = task ? await api.getProject(task.project_id) : null;
      setRunModalProject(project);
      if (project?.aliases?.["default"]) {
        setRunModalAlias("default");
      }
    } catch {
      setRunModalProject(null);
    }
    setRunModal(true);
  };

  const submitRunModal = async () => {
    if (!task || !runModalAlias || !runModalProject) return;
    const cfg = runModalProject.aliases?.[runModalAlias];
    if (!cfg) return;
    let prompt = runModalPrompt;
    if (runs.length === 0 && runModalPrompt.trim()) {
      const desc = (task.description || "").trim();
      prompt = desc ? desc + "\n\n" + runModalPrompt.trim() : runModalPrompt.trim();
    }
    await api.startTask(task.id, {
      flow: cfg.flow_chain?.[0] || "default",
      flow_chain: cfg.flow_chain || ["default"],
      user_prompt: prompt,
      model: cfg.model || "",
      agent: cfg.agent || "cursor",
      step_overrides: cfg.step_overrides || {},
      one_shot: runModalOneShot,
    });
    setRunModal(false);
    setRuns(await api.listTaskRuns(task.id));
  };

  const sortedAliases = () => {
    const aliases = runModalProject?.aliases || {};
    return Object.keys(aliases)
      .sort((a, b) => (a === "default" ? -1 : b === "default" ? 1 : a.localeCompare(b)))
      .map((k) => ({ name: k, ...aliases[k] }));
  };

  const saveDescription = async () => {
    if (!task) return;
    const updated = await api.updateTask(task.id, { description: editDescText });
    setTask(updated);
    setEditingDesc(false);
  };

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => task ? navigate(`/project/${task.project_id}`) : navigate("/")}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            &larr; Back
          </button>
          <h2 className="text-base font-medium">{task?.name || "Loading..."}</h2>
          <span className="text-[10px] uppercase text-gray-500 font-medium">{task?.type}</span>
        </div>
        <button
          onClick={openRunModal}
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition"
        >
          Start Run
        </button>
      </header>

      {/* Description */}
      {task && (
        <div className="px-6 py-3 border-b border-gray-800">
          {!editingDesc ? (
            <div className="flex items-start gap-2">
              <p className="text-sm text-gray-400 flex-1 whitespace-pre-wrap">
                {task.description || <span className="italic text-gray-600">No description</span>}
              </p>
              <button
                onClick={() => { setEditDescText(task.description || ""); setEditingDesc(true); }}
                className="text-xs text-gray-600 hover:text-gray-400 flex-shrink-0"
              >
                Edit
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <textarea
                value={editDescText}
                onChange={(e) => setEditDescText(e.target.value)}
                rows={4}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                autoFocus
              />
              <div className="flex gap-2">
                <button onClick={saveDescription} className="text-xs text-blue-400 hover:text-blue-300">Save</button>
                <button onClick={() => setEditingDesc(false)} className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Runs */}
      <div className="p-6">
        <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
          Runs ({runs.length})
        </h3>
        <div className="space-y-2">
          {runs.map((run) => (
            <div key={run.id} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div
                className="px-5 py-3 flex items-center justify-between cursor-pointer hover:bg-gray-800/50"
                onClick={() => toggleRun(run.id)}
              >
                <div className="flex items-center gap-3">
                  <span className={`text-xs px-2 py-0.5 rounded ${statusBadge(displayStatus(run))}`}>
                    {displayStatus(run)}
                  </span>
                  <span className="text-xs text-cyan-400">{run.flow_name}</span>
                  <span className="text-xs text-gray-500">{duration(run.started_at, run.completed_at)}</span>
                </div>
                <div className="flex items-center gap-2">
                  {isRunActive(run) && (
                    <button
                      onClick={(e) => { e.stopPropagation(); forceStopRun(run.id); }}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Stop
                    </button>
                  )}
                  {run.completed_at && (
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteRun(run.id); }}
                      className="text-xs text-gray-600 hover:text-red-400"
                    >
                      Delete
                    </button>
                  )}
                  <span className="text-xs text-gray-600">{expandedRun === run.id ? "▲" : "▼"}</span>
                </div>
              </div>

              {expandedRun === run.id && (
                <div className="border-t border-gray-800">
                  {/* Step pipeline */}
                  {(runSteps[run.id] || []).length > 0 && (
                    <div className="px-5 py-3 flex items-center gap-1 overflow-x-auto">
                      {(runSteps[run.id] || []).map((step, i) => (
                        <div key={i} className="flex items-center gap-1">
                          {i > 0 && <div className={`w-4 h-0.5 ${stepConnectorClass(step.status)}`} />}
                          <button
                            onClick={() => step.step_run && viewStepLogs(step)}
                            className={`px-2 py-1 rounded border text-[11px] whitespace-nowrap ${stepBoxClass(step.status)} ${
                              step.step_run ? "cursor-pointer hover:opacity-80" : "cursor-default"
                            }`}
                          >
                            {step.name === "__one_shot__" ? "one-shot" : step.name === "__summary__" ? "summary" : step.name}
                            {step.has_ifs && " ⓘ"}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Viewing step indicator */}
                  {viewingStepName && (
                    <div className="px-5 py-1 text-xs text-gray-500 border-t border-gray-800">
                      Viewing: <span className="text-cyan-400">{viewingStepName}</span>
                    </div>
                  )}

                  {/* Log viewer */}
                  <div className="h-80">
                    <LogViewer entries={logEntries} streaming={streaming} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Run Modal */}
      {runModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => setRunModal(false)}>
          <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold mb-4">Start Run</h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 block mb-1">Alias</label>
                <select
                  value={runModalAlias}
                  onChange={(e) => setRunModalAlias(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">Select alias...</option>
                  {sortedAliases().map((a) => (
                    <option key={a.name} value={a.name}>
                      {a.name} ({a.agent}, {a.flow_chain.join(" → ")})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">Additional prompt (optional)</label>
                <textarea
                  value={runModalPrompt}
                  onChange={(e) => setRunModalPrompt(e.target.value)}
                  rows={3}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm resize-none"
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-400">
                <input
                  type="checkbox"
                  checked={runModalOneShot}
                  onChange={(e) => setRunModalOneShot(e.target.checked)}
                  className="rounded"
                />
                One-shot mode
              </label>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setRunModal(false)} className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200">
                Cancel
              </button>
              <button
                onClick={submitRunModal}
                disabled={!runModalAlias}
                className="px-4 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-40"
              >
                Start
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
